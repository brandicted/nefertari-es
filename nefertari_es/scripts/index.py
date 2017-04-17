from argparse import ArgumentParser
import sys
import logging

from pyramid.paster import bootstrap
from pyramid.config import Configurator
from six.moves import urllib

from nefertari.utils import dictset, split_strip
from nefertari import engine


def main(argv=sys.argv):
    logger = logging.getLogger()
    logger.setLevel(logging.WARNING)
    ch = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    command = IndexCommand(argv, logger)
    return command.run()


class IndexCommand(object):
    usage = '%prog config_uri <models'

    def __init__(self, argv, logger):
        parser = ArgumentParser(description=__doc__)
        parser.add_argument(
            '-c', '--config', help='config.ini (required)',
            required=True)
        parser.add_argument(
            '--quiet', help='Quiet mode', action='store_true',
            default=False)
        parser.add_argument(
            '--models',
            help=('Comma-separated list of model names to index '
                  '(required)'),
            required=True)
        parser.add_argument(
            '--params', help='Url-encoded params for each model')
        parser.add_argument(
            '--force',
            help=('Reindex all documents. By default only missing '
                  'documents are indexed.'),
            action='store_true',
            default=False)
        self._prepare_env(parser, logger)

    def _prepare_env(self, parser, logger):
        self.options = parser.parse_args()
        if not self.options.config:
            return parser.print_help()

        env = bootstrap(self.options.config)
        registry = env['registry']
        # Include 'nefertari.engine' to setup engines
        config = Configurator(settings=registry.settings)
        config.include('nefertari.engine')

        self.logger = logger
        if not self.options.quiet:
            self.logger.setLevel(logging.INFO)

        self.settings = dictset(registry.settings)

    def _nefertari_es_secondary(self):
        import nefertari_es
        from nefertari import engine
        return engine.secondary is nefertari_es

    def run(self):
        if not self._nefertari_es_secondary():
            self.logger.warning(
                'Nothing to index: nefertari_es is not a secondary '
                'engine')
            return

        model_names = split_strip(self.options.models)
        for model_name in model_names:
            self._index_model(model_name)

    def _index_model(self, model_name):
        self.logger.info('Processing model `{}`'.format(model_name))
        model = engine.get_document_cls(model_name)
        es_model = model._secondary

        params = self.options.params or ''
        params = dict([
            [k, v[0]] for k, v in urllib.parse.parse_qs(params).items()
        ])
        db_queryset = model.get_collection(
            _query_secondary=False, **params)

        pk_field = es_model.pk_field()
        db_pks = [getattr(dbobj, pk_field) for dbobj in db_queryset]
        es_items = es_model.get_collection(**{pk_field: db_pks})

        if self.options.force:
            self.logger.info('Deleting existing `{}` documents'.format(
                model_name))
            es_model._delete_many(es_items)
            self.logger.info('Indexing all `{}` documents'.format(
                model_name))
            missing_items = [item for item in db_queryset]
        else:
            self.logger.info('Indexing missing `{}` documents'.format(
                model_name))
            es_pks = [str(getattr(doc, pk_field)) for doc in es_items]
            missing_items = [
                item for item in db_queryset
                if str(getattr(item, pk_field)) not in es_pks]

        if not missing_items:
            self.logger.info('Nothing to index')
            return

        self._index_docs(es_model, missing_items)

    def _index_docs(self, es_model, db_items):
        db_items_data = [itm.to_dict(_depth=0) for itm in db_items]
        index_items = []
        for data in db_items_data:
            es_item = es_model(**data)
            es_item._populate_meta_id()
            index_items.append(es_item)
        es_model._index_many(index_items)

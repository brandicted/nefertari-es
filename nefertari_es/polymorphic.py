"""
Module that defines all the objects required to handle polymorphic
collection read requests.

Im particular:
    * PolymorphicACL: Dynamic factory class that generates ACL considering
        ACLs of all the collections requested.
    * PolymorphicView: View that handles polymorphic collection read
        requests.

This module is enabled by including it with Pyramid Configurator and
specifying `elasticsearch.enable_polymorphic_query = true` setting in
your .ini file.

After inclusion, PolymorphicView view will be registered to handle GET
requests. To access polymorphic API endpoint, compose URL with names
used to access collection GET API endpoints.

E.g. If API had collection endpoints '/users' and '/stories', polymorphic
endpoint would be available at '/users,stories' and '/stories,users'.

Polymorphic endpoints support all the read functionality regular ES
endpoint supports: query, search, filter, sort, etc.
"""
from pyramid.security import DENY_ALL, Allow, ALL_PERMISSIONS

from nefertari.view import BaseView
from nefertari.acl import CollectionACL
from nefertari.json_httpexceptions import JHTTPBadRequest
from elasticsearch_dsl import Search

from nefertari_es.documents import BaseDocument
from nefertari_es.aggregation import Aggregator


def includeme(config):
    """ Connect view to route that catches all URIs like
    'collection1,collection2,...'
    """
    root = config.get_root_resource()
    root.add('nefes_polymorphic', '{collections:.+,.+}',
             view=PolymorphicView,
             factory=PolymorphicACL)


class PolymorphicHelperMixin(object):
    """ Helper mixin class that contains methods used by:
        * PolymorphicACL
        * PolymorphicView
    """
    def get_collections(self):
        """ Get names of collections from request matchdict.

        :return: Names of collections
        :rtype: list of str
        """
        collections = self.request.matchdict['collections'].split('/')[0]
        collections = [coll.strip() for coll in collections.split(',')]
        return set(collections)

    def get_resources(self, collections):
        """ Get resources that correspond to values from :collections:.

        :param collections: Collection names for which resources should be
            gathered
        :type collections: list of str
        :return: Gathered resources
        :rtype: list of Resource instances
        """
        res_map = self.request.registry._model_collections
        resources = [res for res in res_map.values()
                     if res.collection_name in collections]
        resources = [res for res in resources if res]
        return set(resources)


class PolymorphicACL(PolymorphicHelperMixin, CollectionACL):
    """ ACL used by PolymorphicView.

    Generates ACEs checking whether current request user has 'view'
    permissions in all of the requested collection views/contexts.
    """
    def __init__(self, request):
        """ Set ACL generated from collections affected. """
        super(PolymorphicACL, self).__init__(request)
        self.set_collections_acl()

    def _get_least_permissions_aces(self, resources):
        """ Get ACEs with the least permissions that fit all resources.

        To have access to polymorph on N collections, user MUST have
        access to all of them. If this is true, ACEs are returned, that
        allows 'view' permissions to current request principals.

        Otherwise None is returned thus blocking all permissions except
        those defined in `nefertari.acl.BaseACL`.

        :param resources:
        :type resources: list of Resource instances
        :return: Generated Pyramid ACEs or None
        :rtype: tuple or None
        """
        factories = [res.view._factory for res in resources]
        contexts = [factory(self.request) for factory in factories]
        for ctx in contexts:
            if not self.request.has_permission('view', ctx):
                return
        else:
            return [
                (Allow, principal, 'view')
                for principal in self.request.effective_principals
            ]

    def set_collections_acl(self):
        """ Calculate and set ACL valid for requested collections.

        DENY_ALL is added to ACL to make sure no access rules are
        inherited.
        """
        acl = [(Allow, 'g:admin', ALL_PERMISSIONS)]
        collections = self.get_collections()
        resources = self.get_resources(collections)
        aces = self._get_least_permissions_aces(resources)
        if aces is not None:
            for ace in aces:
                acl.append(ace)
        acl.append(DENY_ALL)
        self.__acl__ = tuple(acl)


class PolymorphicView(PolymorphicHelperMixin, BaseView):
    """ Polymorphic collection read view.

    Has default implementation of 'index' view method that supports
    all the ES collection read actions(query, count, etc.) across
    multiple collections of documents.

    To be displayed by polymorphic view, model must have collection view
    setup that serves instances of this model. Models that only have
    singular views setup are not served by polymorhic view.
    """
    def __init__(self, *args, **kwargs):
        super(PolymorphicView, self).__init__(*args, **kwargs)
        self.es_models = self.get_es_models()

    def _run_init_actions(self):
        self.setup_default_wrappers()
        self.set_public_limits()

    def _setup_aggregation(self, *args, **kwargs):
        kwargs['aggregator'] = PolymorphicAggregator
        super(PolymorphicView, self)._setup_aggregation(*args, **kwargs)

    def get_es_models(self):
        """ Determine ES models from request data.

        In particular `request.matchdict['collections']` is used to
        determine types names. Its value is comma-separated sequence
        of collection names under which views have been registered.

        :returns: List of ES document types.
        """
        collections = self.get_collections()
        resources = self.get_resources(collections)
        models = set([res.view.Model for res in resources])
        models = [mdl for mdl in models if mdl is not None]
        es_models = []
        for model in models:
            if not issubclass(model, BaseDocument):
                model = model._secondary
            es_models.append(model)
        return es_models

    def index(self, collections):
        """ Handle collection GET request. """
        self._query_params.process_int_param('_limit', 20)
        return BaseDocument.get_collection(
            search_obj=Search(doc_type=self.es_models),
            **self._query_params)


class PolymorphicAggregator(Aggregator):
    def aggregate(self):
        """ Perform aggregation and return response. """
        es_models = self.view.es_models
        if not es_models:
            raise JHTTPBadRequest('No ES-based model defined')

        aggregations_params = self.pop_aggregations_params()
        if self.view._auth_enabled:
            for model in es_models:
                self.check_aggregations_privacy(
                    aggregations_params, model)
        self.stub_wrappers()

        return BaseDocument.aggregate(
            _aggs_params=aggregations_params,
            search_obj=Search(doc_type=es_models),
            **self._query_params)

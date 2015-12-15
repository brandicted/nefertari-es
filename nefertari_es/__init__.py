from __future__ import absolute_import

from elasticsearch_dsl.connections import connections as es_connections
from nefertari.utils import (
    dictset,
    split_strip,
)
from .documents import BaseDocument
from .serializers import get_json_serializer
from .connections import ESHttpConnection
from .meta import (
    get_document_cls,
    get_document_classes,
    create_index,
)
from .utils import (
    is_relationship_field,
    get_relationship_cls,
    relationship_fields,
)
from .fields import (
    IdField,
    IntervalField,
    DictField,
    DateTimeField,
    DateField,
    TimeField,
    IntegerField,
    SmallIntegerField,
    StringField,
    TextField,
    UnicodeField,
    UnicodeTextField,
    BigIntegerField,
    BooleanField,
    FloatField,
    BinaryField,
    DecimalField,
    ReferenceField,
    Relationship,

    ListField,
    ForeignKeyField,
    ChoiceField,
    PickleField,
)

from nefertari.engine.common import JSONEncoder


__all__ = [
    'BaseDocument',
    'IdField',
    'IntervalField',
    'DictField',
    'DateTimeField',
    'DateField',
    'TimeField',
    'IntegerField',
    'SmallIntegerField',
    'StringField',
    'TextField',
    'UnicodeField',
    'UnicodeTextField',
    'BigIntegerField',
    'BooleanField',
    'FloatField',
    'BinaryField',
    'DecimalField',
    'ReferenceField',
    'Relationship',
    'setup_database',
    'get_document_cls',
    'get_document_classes',
    'is_relationship_field',
    'get_relationship_cls',
    'relationship_fields',
    'JSONEncoder',

    'ListField',
    'ForeignKeyField',
    'ChoiceField',
    'PickleField',
]


Settings = dictset()


def includeme(config):
    config.include('nefertari_es.sync_handlers')
    settings = dictset(config.registry.settings).mget('elasticsearch')
    Settings.update(settings)


def setup_database(config):
    params = {}
    params['chunk_size'] = Settings.get('chunk_size', 500)
    params['hosts'] = []
    for hp in split_strip(Settings['hosts']):
        h, p = split_strip(hp, ':')
        params['hosts'].append(dict(host=h, port=p))
    if Settings.asbool('sniff'):
        params['sniff_on_start'] = True
        params['sniff_on_connection_fail'] = True

    serializer_cls = get_json_serializer()
    conn = es_connections.create_connection(
        serializer=serializer_cls(),
        connection_class=ESHttpConnection,
        **params)
    setup_index(conn)

    if Settings.asbool('enable_polymorphic_query'):
        config.include('nefertari_es.polymorphic')


def setup_index(conn):
    from nefertari.json_httpexceptions import JHTTPNotFound
    index_name = Settings['index_name']
    try:
        index_exists = conn.indices.exists([index_name])
    except JHTTPNotFound:
        index_exists = False
    if not index_exists:
        create_index(index_name)
    else:
        for doc_cls in get_document_classes().values():
            doc_cls._doc_type.index = index_name

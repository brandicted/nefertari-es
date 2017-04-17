import inspect

from elasticsearch_dsl import Index
from elasticsearch_dsl.document import DocTypeMeta as ESDocTypeMeta
from elasticsearch_dsl.field import Field
from nefertari.engine.common import MultiEngineMeta

# BaseDocument subclasses registry
# maps class names to classes
_document_registry = {}


def create_index(index_name, doc_classes=None):
    """ Create index and add document classes to it.

    Does NOT check whether index already exists.

    :param index_name: Name of index to be created.
    :param doc_classes: Sequence of document classes which should be
        added to created index. Defaults to None, in which case all
        document classes from document registry are added to new index.
    """
    index = Index(index_name)

    if doc_classes is None:
        doc_classes = get_document_classes().values()

    for doc_cls in doc_classes:
        index.doc_type(doc_cls)

    index.create()


def get_document_cls(name):
    """ Get BaseDocument subclass from document registry.

    :param name: String name of BaseDocument subclass to get
    :returns: BaseDocument subclass of name :name:
    :raises KeyError: If document class is not defined
    """
    return _document_registry[name]


def get_document_classes():
    """ Get all defined not abstract document classes. """
    return _document_registry.copy()


class RegisteredDocMixin(type):
    """ Metaclass mixin that registers defined doctypes in
    ``_document_registry``.
    """
    def __new__(cls, name, bases, attrs):
        new_class = super(RegisteredDocMixin, cls).__new__(
            cls, name, bases, attrs)
        _document_registry[new_class.__name__] = new_class
        return new_class


class NonDocumentInheritanceMixin(type):
    """ Metaclass mixin that adds class attribute fields to mapping
    of they are not there yet.

    Is useful when inheriting non-DocType subclasses which define
    fields.
    """
    def __new__(cls, name, bases, attrs):
        """ Override to fix errors on when inheriting non-doctype.

        Im particular:
          * Check for all Field instances, move them to mapping and
            replace attributes with descriptor that raises
            AttributeError.
          * Replace all attributes that have names of mapping fields
            with descriptor that raises AttributeError.
        """
        new_cls = super(NonDocumentInheritanceMixin, cls).__new__(
            cls, name, bases, attrs)
        mapping = new_cls._doc_type.mapping

        class AttrErrorDescriptor(object):
            def __get__(self, *args, **kwargs):
                raise AttributeError

        for name, member in inspect.getmembers(new_cls):
            if name.startswith('__') or name in mapping:
                continue
            if isinstance(member, Field):
                mapping.field(name, member)
                setattr(new_cls, name, AttrErrorDescriptor())

        for name in mapping:
            if hasattr(new_cls, name):
                setattr(new_cls, name, AttrErrorDescriptor())

        return new_cls


class BackrefGeneratingDocMixin(type):
    """ Metaclass mixin that generates relationship backrefs. """
    def __new__(cls, name, bases, attrs):
        from .fields import Relationship
        new_class = super(BackrefGeneratingDocMixin, cls).__new__(
            cls, name, bases, attrs)

        relationships = new_class._relationships()
        for name in relationships:
            field = new_class._doc_type.mapping[name]
            if not field._backref_kwargs:
                continue
            target_cls = field._doc_class
            backref_kwargs = field._backref_kwargs.copy()
            field_name = backref_kwargs.pop('name')
            backref_kwargs.setdefault('uselist', False)
            backref_field = Relationship(
                new_class.__name__, **backref_kwargs)
            backref_field._is_backref = True
            backref_field._back_populates = name
            target_cls._doc_type.mapping.field(field_name, backref_field)
            field._back_populates = field_name

        return new_class


class GenerateMetaMixin(type):
    """ Metaclass mixin that generates Meta class attribute.

    Also restores '__abstract__' param to default ``False`` if not
    explicitly defined.
    """
    def __new__(cls, name, bases, attrs):
        attrs.setdefault('__abstract__', False)
        if 'Meta' not in attrs:

            class Meta(object):
                doc_type = name

            attrs['Meta'] = Meta
        return super(GenerateMetaMixin, cls).__new__(
            cls, name, bases, attrs)


class DocTypeMeta(
        GenerateMetaMixin,
        NonDocumentInheritanceMixin,
        RegisteredDocMixin,
        BackrefGeneratingDocMixin,
        MultiEngineMeta,
        ESDocTypeMeta):
    pass

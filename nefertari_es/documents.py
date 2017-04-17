from functools import partial
import copy

from six import (
    with_metaclass,
)
from elasticsearch_dsl import DocType
from elasticsearch_dsl.utils import AttrList, AttrDict
from elasticsearch_dsl.field import InnerObjectWrapper
from elasticsearch_dsl.connections import connections as es_connections
from elasticsearch import helpers
from nefertari.json_httpexceptions import (
    JHTTPBadRequest,
    JHTTPNotFound,
)
from nefertari.utils import (
    process_fields,
    process_limit,
    dictset,
    split_strip,
)
from nefertari.engine.common import MultiEngineDocMixin

from .meta import DocTypeMeta
from .fields import (
    ReferenceField, IdField, DictField, ListField,
    IntegerField, Relationship
)
from .utils import relationship_fields


class SyncRelatedMixin(object):
    _backref_hooks = ()
    _created = False

    def __init__(self, *args, **kwargs):
        _created = 'meta' not in kwargs
        super(SyncRelatedMixin, self).__init__(*args, **kwargs)
        if not _created:
            return
        for field_name in self._relationships():
            if field_name not in kwargs:
                continue
            new_value = kwargs[field_name]
            if new_value not in ([], {}, None):
                field_obj = self._doc_type.mapping[field_name]
                self._d_[field_name] = field_obj.empty()
                setattr(self, field_name, new_value)
        self._created = _created

    def __setattr__(self, name, value):
        if name in self._relationships():

            # Load new value from db
            data = {name: value}
            self._load_related(name, container=data)
            value = data[name]

            # Load existing data from db
            self._load_related(name)
            self._sync_related(
                new_value=value,
                old_value=self._d_.get(name),
                field_name=name)
        super(SyncRelatedMixin, self).__setattr__(name, value)

    def _sync_related(self, new_value, old_value, field_name):
        field = self._doc_type.mapping[field_name]
        if not field._back_populates:
            return
        if not isinstance(new_value, (list, AttrList)):
            new_value = [new_value] if new_value else []
        if not isinstance(old_value, (list, AttrList)):
            old_value = [old_value] if old_value else []

        added_values = set(new_value) - set(old_value)
        deleted_values = set(old_value) - set(new_value)

        if added_values:
            for val in added_values:
                self._register_addition_hook(val, field._back_populates)

        if deleted_values:
            for val in deleted_values:
                self._register_deletion_hook(val, field._back_populates)

    @staticmethod
    def _addition_hook(_item, _add_item, _field_name):
        field = _item._doc_type.mapping[_field_name]
        curr_val = getattr(_item, _field_name, None)
        if field._multi:
            new_val = list(curr_val or [])
            if _add_item not in new_val:
                new_val.append(_add_item)
        else:
            new_val = (_add_item if _add_item != curr_val
                       else curr_val)

        value_changed = (
            (field._multi and set(curr_val or []) != set(new_val)) or
            (not field._multi and curr_val != new_val))
        if value_changed:
            _item.update({_field_name: new_val})

    def _register_addition_hook(self, item, field_name):
        """ Register hook to add `self` to `item` field `field_name`. """
        _hook = partial(
            self.__class__._addition_hook,
            _item=item,
            _add_item=self,
            _field_name=field_name)
        self._backref_hooks += (_hook,)

    @staticmethod
    def _deletion_hook(_item, _del_item, _field_name):
        curr_val = getattr(_item, _field_name, None)
        if not curr_val:
            return

        field = _item._doc_type.mapping[_field_name]
        if field._multi:
            new_val = list(curr_val or [])
            if _del_item in new_val:
                new_val.remove(_del_item)
        else:
            new_val = (None if _del_item == curr_val
                       else curr_val)

        value_changed = (
            (field._multi and set(curr_val or []) != set(new_val)) or
            (not field._multi and curr_val != new_val))
        if value_changed:
            _item.update({_field_name: new_val})

    def _register_deletion_hook(self, item, field_name):
        """ Register hook to delete `self` from `item` field
        `field_name`.
        """
        _hook = partial(
            self.__class__._deletion_hook,
            _item=item,
            _del_item=self,
            _field_name=field_name)
        self._backref_hooks += (_hook,)

    def save(self, *args, **kwargs):
        try:
            obj = super(SyncRelatedMixin, self).save(*args, **kwargs)
        except:
            raise
        else:
            for hook in self._backref_hooks:
                hook()
            self._backref_hooks = ()
            return obj


class VersionedMixin(object):
    """ Mixin that adds "version" field. """
    version = IntegerField()

    def _bump_version(self):
        if self._is_modified():
            self.version = (self.version or 0) + 1

    def save(self, *args, **kwargs):
        self._bump_version()
        return super(VersionedMixin, self).save(*args, **kwargs)

    @classmethod
    def get_null_values(cls):
        null_values = super(VersionedMixin, cls).get_null_values()
        null_values.pop('version', None)
        return null_values

    def __repr__(self):
        name = super(VersionedMixin, self).__repr__()
        if hasattr(self, 'version'):
            name.replace('>', ', v=%s>' % self.version)
        return name


class BaseMixin(object):
    _sync_events = None
    _public_fields = None
    _auth_fields = None
    _hidden_fields = None
    _nested_relationships = ()
    _nesting_depth = 1
    _request = None

    def __init__(self, *args, **kwargs):
        self._pop_db_meta(kwargs)
        super(BaseMixin, self).__init__(*args, **kwargs)
        self._populate_id_field()

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            pk_field = self.pk_field()
            self_pk = getattr(self, pk_field, None)
            other_pk = getattr(other, pk_field, None)
            return (self_pk is not None and other_pk is not None
                    and self_pk == other_pk)
        return super(BaseMixin, self).__eq__(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def __hash__(self):
        pk_field = self.pk_field()
        pk = getattr(self, pk_field, None)
        if pk is None:
            self._populate_id_field()
            pk = getattr(self, pk_field, None)
            if pk is None:
                return None

        def _hasher():
            cls_name = self.__class__.__name__
            return hash(cls_name + str(pk))

        return _hasher

    def _pop_db_meta(self, kw):
        for key in ('_type', '_version', '_pk'):
            kw.pop(key, None)

    def _populate_meta_id(self):
        """ Copy PK field value to meta["id"]. """
        pk_value = getattr(self, self.pk_field(), None)
        if pk_value not in (None, ''):
            self.meta['id'] = pk_value

    def _populate_id_field(self):
        """ Copy meta["id"] to IdField. """
        if self.pk_field_type() is IdField:
            pk_field = self.pk_field()
            if not getattr(self, pk_field, None) and self._id is not None:
                self._d_[pk_field] = str(self._id)

    def __setattr__(self, name, value):
        if name == self.pk_field() and self.pk_field_type() == IdField:
            raise AttributeError('{} is read-only'.format(self.pk_field()))
        super(BaseMixin, self).__setattr__(name, value)

    def __getattr__(self, name):
        if name == '_id' and 'id' not in self.meta:
            return None
        if name in self._relationships():
            self._load_related(name)
        return super(BaseMixin, self).__getattr__(name)

    def __repr__(self):
        parts = ['%s:' % self.__class__.__name__]
        pk_field = self.pk_field()
        parts.append('{}={}'.format(pk_field, getattr(self, pk_field)))
        return '<%s>' % ', '.join(parts)

    def _getattr_raw(self, name):
        return self._d_[name]

    def _unload_related(self, field_name):
        value = field_name in self._d_ and self._d_[field_name]
        if not value:
            return

        field = self._doc_type.mapping[field_name]
        doc_cls = field._doc_class
        if not isinstance(value, (list, AttrList)):
            value = [value]

        if isinstance(value[0], doc_cls):
            pk_field = doc_cls.pk_field()
            items = [getattr(item, pk_field, None) for item in value]
            items = [item for item in items if item is not None]
            if items:
                self._d_[field_name] = items if field._multi else items[0]

    def _load_related(self, field_name, container=None):
        if container is None:
            container = self._d_

        value = field_name in container and container[field_name]
        if not value:
            return

        field = self._doc_type.mapping[field_name]
        doc_cls = field._doc_class
        if not isinstance(value, (list, AttrList)):
            value = [value]

        if not isinstance(value[0], doc_cls):
            pk_field = doc_cls.pk_field()
            items = doc_cls.get_collection(
                **{pk_field: value, '_query_secondary': False})
            if items:
                container[field_name] = items if field._multi else items[0]

    def to_dict(self, include_meta=False, _keys=None, request=None,
                _depth=None):
        """
        DocType and nefertari both expect a to_dict method, but
        they expect it to act differently. DocType uses to_dict for
        serialize for saving to es. nefertari uses it to serialize
        for serving JSON to the client. For now we differentiate by
        looking for a request argument. If it's present we assume
        that we're serving JSON to the client, otherwise we assume
        that we're saving to es
        """
        if _depth is None:
            _depth = self._nesting_depth
        depth_reached = _depth is not None and _depth <= 0
        if request is None:
            request = self._request

        for name in self._relationships():
            include = (request is not None and
                       name in self._nested_relationships and
                       not depth_reached)
            if not include:
                self._unload_related(name)
                continue

            # Related document is implicitly loaded on __getattr__
            value = getattr(self, name)
            if value:
                if not isinstance(value, (list, AttrList)):
                    value = [value]
                for val in value:
                    try:
                        val._nesting_depth = _depth - 1
                        val._request = request
                    except AttributeError:
                        continue

        data = super(BaseMixin, self).to_dict(include_meta=include_meta)
        data = {key: val for key, val in data.items()
                if not key.startswith('__')}

        if request is not None and '_type' not in data:
            data['_type'] = self.__class__.__name__
        if request is not None:
            data['_pk'] = str(getattr(self, self.pk_field()))
        return data

    @classmethod
    def _flatten_relationships(cls, params):
        for name in cls._relationships():
            if name not in params:
                continue
            inst = params[name]
            field_obj = cls._doc_type.mapping[name]
            pk_field = field_obj._doc_class.pk_field()
            if isinstance(inst, (list, AttrList)):
                params[name] = [getattr(i, pk_field, i) for i in inst]
            else:
                params[name] = getattr(inst, pk_field, inst)
        return params

    @classmethod
    def _get_fields_creators(cls):
        """ Return map of field creator classes/functions.

        Map consists of:
            field name: String name of a field
            field creator: Class/func that may be run to create new
                instance of such field. Note that these are classes that
                create fields, not classes of created fields. E.g.
                "Relationship" func instead of "ReferenceField".

        Does not return backref relationship fields.
        """
        fields = {name: cls._doc_type.mapping[name]
                  for name in cls._doc_type.mapping}

        backrefs = [
            key for key, val in fields.items()
            if (isinstance(val, relationship_fields) and
                getattr(val, '_is_backref', False))]
        fields = {key: type(val) for key, val in fields.items()}
        for key in fields:
            if fields[key] in relationship_fields:
                fields[key] = Relationship
        for name in backrefs:
            fields.pop(name, None)
        return fields

    @classmethod
    def _relationships(cls):
        return [
            name for name in cls._doc_type.mapping
            if isinstance(cls._doc_type.mapping[name], ReferenceField)]

    @classmethod
    def pk_field(cls):
        for name in cls._doc_type.mapping:
            field = cls._doc_type.mapping[name]
            if getattr(field, '_primary_key', False):
                return name
        else:
            raise AttributeError('No primary key field')

    @classmethod
    def pk_field_type(cls):
        pk_field = cls.pk_field()
        return cls._doc_type.mapping[pk_field].__class__

    @classmethod
    def get_item(cls, **kw):
        """ Get single item and raise exception if not found.

        Exception raising when item is not found can be disabled
        by passing ``_raise_on_empty=False`` in params.

        :returns: Single collection item as an instance of ``cls``.
        """
        kw.setdefault('_raise_on_empty', True)
        items = cls.get_collection(_limit=1, _item_request=True, **kw)
        return items[0]

    @classmethod
    def _update_many(cls, items, params, request=None):
        return cls._bulk_operation(items, 'update', request, params)

    @classmethod
    def _delete_many(cls, items, request=None):
        return cls._bulk_operation(items, 'delete', request)

    @classmethod
    def _index_many(cls, items, request=None):
        return cls._bulk_operation(items, 'index', request)

    @classmethod
    def _bulk_operation(cls, items, op_type, request=None, params=None):
        if params is not None:
            params = cls._flatten_relationships(params)

        if not items:
            return

        actions = [item.to_dict(include_meta=True) for item in items]
        actions_count = len(actions)
        if params is not None:
            for action in actions:
                action.pop('_source')
                action['doc'] = params

        client = items[0].connection
        operation = partial(
            _bulk,
            client=client, op_type=op_type, request=request)
        _perform_in_chunks(actions, operation)
        return actions_count

    @classmethod
    def get_collection(cls, _count=False, _strict=True, _sort=None,
                       _fields=None, _limit=None, _page=None, _start=None,
                       _query_set=None, _item_request=False, _explain=None,
                       _search_fields=None, q=None, _raise_on_empty=False,
                       search_obj=None, **params):
        """ Query collection and return results.

        Notes:
        *   Before validating that only model fields are present in params,
            reserved params, query params and all params starting with
            double underscore are dropped.
        *   Params which have value "_all" are dropped.
        *   When ``_count`` param is used, objects count is returned
            before applying offset and limit.

        :param bool _strict: If True ``params`` are validated to contain
            only fields defined on model, exception is raised if invalid
            fields are present. When False - invalid fields are dropped.
            Defaults to ``True``.
        :param list _sort: Field names to sort results by. If field name
            is prefixed with "-" it is used for "descending" sorting.
            Otherwise "ascending" sorting is performed by that field.
            Defaults to an empty list in which case sorting is not
            performed.
        :param list _fields: Names of fields which should be included
            or excluded from results. Fields to excluded should be
            prefixed with "-". Defaults to an empty list in which
            case all fields are returned.
        :param int _limit: Number of results per page. Defaults
            to None in which case all results are returned.
        :param int _page: Number of page. In conjunction with
            ``_limit`` is used to calculate results offset. Defaults to
            None in which case it is ignored. Params ``_page`` and
            ``_start` are mutually exclusive.
        :param int _start: Results offset. If provided ``_limit`` and
            ``_page`` params are ignored when calculating offset. Defaults
            to None. Params ``_page`` and ``_start`` are mutually
            exclusive. If not offset-related params are provided, offset
            equals to 0.
        :param Query _query_set: Existing queryset. If provided, all queries
            are applied to it instead of creating new queryset. Defaults
            to None.
        :param bool _item_request: Indicates whether it is a single item
            request or not. When True and DataError happens on DB request,
            JHTTPNotFound is raised. JHTTPBadRequest is raised when False.
            Defaults to ``False``.
        :param _count: When provided, only results number is returned as
            integer.
        :param _explain: When provided, query performed(SQL) is returned
            as a string instead of query results.
        :param bool _raise_on_empty: When True JHTTPNotFound is raised
            if query returned no results. Defaults to False in which case
            error is just logged and empty query results are returned.
        :param q: Query string to perform full-text search with.
        :param _search_fields: Coma-separated list of field names to use
            with full-text search(q param) to limit fields which are
            searched.
        :param search_obj: Instance of elasticsearch_dsl.Search which
            should be used instead of creating new one with cls.search().

        :returns: Query results. May be sorted, offset, limited.
        :returns: Dict of {'field_name': fieldval}, when ``_fields`` param
            is provided.
        :returns: Number of query results as an int when ``_count`` param
            is provided.

        :raises JHTTPNotFound: When ``_raise_on_empty=True`` and no
            results found.
        :raises JHTTPNotFound: When ``_item_request=True`` and
            ``sqlalchemy.exc.DataError`` exception is raised during DB
            query. Latter exception is raised when querying DB with
            an identifier of a wrong type. E.g. when querying Int field
            with a string.
        :raises JHTTPBadRequest: When ``_item_request=False`` and
            ``sqlalchemy.exc.DataError`` exception is raised during DB
            query.
        :raises JHTTPBadRequest: When ``sqlalchemy.exc.InvalidRequestError``
            or ``sqlalchemy.exc.IntegrityError`` errors happen during DB
            query.
        """
        search_passed = search_obj is not None
        if not search_passed:
            search_obj = cls.search()

        if _limit is not None:
            _start, limit = process_limit(_start, _page, _limit)
            search_obj = search_obj.extra(from_=_start, size=limit)

        if _fields:
            search_obj = cls._apply_search_fields(
                search_obj, _fields, _strict, search_passed)

        if params:
            search_obj = cls._apply_search_params(
                search_obj, _strict, search_passed, **params)

        if q is not None:
            search_obj = cls._apply_search_query(
                search_obj, q, _search_fields)

        if _count:
            return search_obj.count()

        if _explain:
            return search_obj.to_dict()

        if _sort:
            sort_fields = split_strip(_sort)
            if _strict and not search_passed:
                clean_fields = [f[1:] if f.startswith('-') else f
                                for f in sort_fields]
                _validate_fields(cls, clean_fields)
            search_obj = search_obj.sort(*sort_fields)

        hits = search_obj.execute().hits
        if not hits and _raise_on_empty:
            msg = "'%s(%s)' resource not found" % (cls.__name__, params)
            raise JHTTPNotFound(msg)

        hits._nefertari_meta = dict(
            total=hits.total,
            start=_start,
            fields=_fields)
        return hits

    @classmethod
    def _apply_search_fields(cls, search_obj, _fields, _strict,
                             search_passed):
        include, exclude = process_fields(_fields)
        if _strict and not search_passed:
            _validate_fields(cls, include + exclude)
        # XXX partial fields support isn't yet released. for now
        # we just use fields, later we'll add support for excluded fields
        return search_obj.fields(include)

    @classmethod
    def _apply_search_query(cls, search_obj, q, _search_fields):
        query_kw = {'query': q}
        if _search_fields is not None:
            query_kw['fields'] = split_strip(_search_fields)
        return search_obj.query('query_string', **query_kw)

    @classmethod
    def _apply_search_params(cls, search_obj, _strict, search_passed,
                             **params):
        params = {key: val for key, val in params.items()
                  if not key.startswith('__') and val != '_all'}
        # process_lists(params)
        process_bools(params)
        if not search_passed:
            params = _clean_query_params(cls, params, _strict)
            params = _rename_pk_param(cls, params)
        params = _restructure_params(params)
        if params:
            search_obj = search_obj.filter('terms', **params)
        return search_obj

    @classmethod
    def aggregate(cls, _aggs_params, _strict=False, _fields=None,
                  q=None, _search_fields=None, search_obj=None,
                  _search_type='count', **params):
        """ Perform aggreration

        Arguments:
            :_aggs_params: Dict of aggregation params. Root key is an
                aggregation name. Required.
            :_search_type: Type of search to use. Optional, defaults to
                'count'. You might want to provide this argument explicitly
                when performing nested aggregations on buckets.
        """
        params.pop('_limit', None)
        search_passed = search_obj is not None
        if search_obj is None:
            search_obj = cls.search()

        # Set limit so ES won't complain. It is ignored in the end
        search_obj.update_from_dict({'aggregations': _aggs_params})
        search_obj = search_obj.params(search_type=_search_type)
        if _fields:
            search_obj = cls._apply_search_fields(
                search_obj, _fields, _strict, search_passed)

        if params:
            search_obj = cls._apply_search_params(
                search_obj, _strict, search_passed, **params)

        if q is not None:
            search_obj = cls._apply_search_query(
                search_obj, q, _search_fields)

        response = search_obj.execute()
        return response.aggregations

    @classmethod
    def get_by_ids(cls, ids, **params):
        params[cls.pk_field()] = ids
        return cls.get_collection(**params)

    @classmethod
    def get_field_params(cls, field_name):
        if field_name in cls._doc_type.mapping:
            field = cls._doc_type.mapping[field_name]
            return getattr(field, '_init_kwargs', None)

    @classmethod
    def fields_to_query(cls):
        return set(cls._doc_type.mapping).union({'_id'})

    @classmethod
    def count(cls, query_set):
        try:
            return query_set.count()
        except AttributeError:
            return len(query_set)

    @classmethod
    def has_field(cls, field):
        return field in cls._doc_type.mapping

    @classmethod
    def get_or_create(cls, request=None, **params):
        defaults = params.pop('defaults', {})
        items = cls.get_collection(
            _query_secondary=False, _raise_on_empty=False,
            **params)
        if not items:
            defaults.update(params)
            return cls(**defaults).save(request=request), True
        elif len(items) > 1:
            raise JHTTPBadRequest('Bad or Insufficient Params')
        else:
            return items[0], False

    @classmethod
    def get_null_values(cls):
        """ Get null values of :cls: fields. """
        skip_fields = {'_acl'}
        null_values = {}
        for name in cls._doc_type.mapping:
            if name in skip_fields:
                continue
            field = cls._doc_type.mapping[name]
            null_values[name] = field.empty()
        null_values.pop('id', None)
        return null_values

    def update_iterables(self, params, attr, unique=False,
                         value_type=None, save=True,
                         request=None):
        field = self._doc_type.mapping[attr]
        is_dict = isinstance(field, DictField)
        is_list = isinstance(field, ListField)

        def split_keys(keys):
            neg_keys = []
            pos_keys = []

            for key in keys:
                if key.startswith('__'):
                    continue
                if key.startswith('-'):
                    neg_keys.append(key[1:])
                else:
                    pos_keys.append(key.strip())
            return pos_keys, neg_keys

        def update_dict(update_params):
            final_value = getattr(self, attr, {}) or {}
            if isinstance(final_value, (InnerObjectWrapper, AttrDict)):
                final_value = final_value.to_dict()
            else:
                final_value = final_value.copy()
            if isinstance(update_params, (InnerObjectWrapper, AttrDict)):
                update_params = update_params.to_dict()

            if update_params in (None, '', {}):
                if not final_value:
                    return
                update_params = {
                    '-' + key: val for key, val in final_value.items()}
            positive, negative = split_keys(list(update_params.keys()))

            # Pop negative keys
            for key in negative:
                final_value.pop(key, None)

            # Set positive keys
            for key in positive:
                final_value[str(key)] = update_params[key]

            setattr(self, attr, final_value)
            if save:
                self.save(request)

        def update_list(update_params):
            final_value = getattr(self, attr, []) or []
            final_value = list(final_value)
            final_value = copy.deepcopy(final_value)
            if update_params in (None, '', []):
                if not final_value:
                    return
                update_params = ['-' + val for val in final_value]
            if isinstance(update_params, dict):
                keys = list(update_params.keys())
            else:
                keys = update_params

            positive, negative = split_keys(keys)

            if not (positive + negative):
                raise JHTTPBadRequest('Missing params')

            if positive:
                if unique:
                    positive = [v for v in positive if v not in final_value]
                final_value += positive

            if negative:
                final_value = list(set(final_value) - set(negative))

            setattr(self, attr, final_value)
            if save:
                self.save(request)

        if is_dict:
            update_dict(params)

        elif is_list:
            update_list(params)

    def _is_modified(self):
        """ Determine if instance is modified.

        TODO: Rework to make the check more sane.
        """
        return not self._is_created()

    def _is_created(self):
        return self._created


class BaseDocument(with_metaclass(
        DocTypeMeta,
        MultiEngineDocMixin, BaseMixin, VersionedMixin, SyncRelatedMixin,
        DocType)):
    __abstract__ = True

    @classmethod
    def _is_abstract(cls):
        return cls.__dict__.get('__abstract__', False)

    def save(self, request=None, refresh=True, **kwargs):
        self._populate_meta_id()
        super(BaseDocument, self).save(refresh=refresh, **kwargs)
        self._populate_id_field()
        return self

    def _update(self, params):
        pk_field = self.pk_field()
        iter_types = (DictField, ListField)
        iter_fields = [
            field for field in self._doc_type.mapping
            if isinstance(self._doc_type.mapping[field], iter_types)]

        for key, value in params.items():
            if key == pk_field:
                continue
            if key in iter_fields:
                self.update_iterables(value, key, unique=True, save=False)
            else:
                setattr(self, key, value)

    def update(self, params, **kw):
        self._pop_db_meta(params)
        process_bools(params)
        _validate_fields(self.__class__, params.keys())
        self._update(params)
        return self.save(**kw)

    def delete(self, request=None):
        super(BaseDocument, self).delete()


def _clean_query_params(cls, params, strict):
    if strict:
        _validate_fields(cls, params.keys())
    else:
        field_names = frozenset(cls.fields_to_query())
        param_names = frozenset(params.keys())
        invalid_params = param_names.difference(field_names)
        for key in invalid_params:
            del params[key]
    return params


def _rename_pk_param(cls, params):
    pk_field = cls.pk_field()
    if pk_field in params:
        field_obj = cls._doc_type.mapping[pk_field]
        if isinstance(field_obj, IdField):
            params['_id'] = params.pop(pk_field)
    return params


def _restructure_params(params):
    for field, param in params.items():
        if not isinstance(param, list):
            params[field] = [param]
    return params


def _validate_fields(cls, field_names):
    valid_names = frozenset(cls.fields_to_query())
    names = frozenset(field_names)
    invalid_names = names.difference(valid_names)
    if invalid_names:
        raise JHTTPBadRequest(
            "'%s' object does not have fields: %s" % (
            cls.__name__, ', '.join(invalid_names)))


def _perform_in_chunks(actions, operation, chunk_size=None):
    if chunk_size is None:
        from nefertari_es import ESSettings
        chunk_size = ESSettings.asint('chunk_size', 500)

    start = end = 0
    count = len(actions)

    while count:
        if count < chunk_size:
            chunk_size = count
        end += chunk_size

        operation(actions=actions[start:end])

        start += chunk_size
        count -= chunk_size


def _bulk(actions, client, op_type='index', request=None):
    from nefertari_es import ESSettings
    for action in actions:
        action['_op_type'] = op_type

    kwargs = {
        'client': client,
        'actions': actions,
    }

    if request is None:
        query_params = {}
    else:
        query_params = request.params.mixed()
    query_params = dictset(query_params)
    refresh_enabled = ESSettings.asbool('enable_refresh_query', False)
    if '_refresh_index' in query_params and refresh_enabled:
        kwargs['refresh'] = query_params.asbool('_refresh_index')

    executed_num, errors = helpers.bulk(**kwargs)
    if errors:
        raise Exception('Errors happened when executing Elasticsearch '
                        'actions: {}'.format('; '.join(errors)))
    return executed_num


def process_bools(_dict):
    for k in _dict:
        new_k, _, _t = k.partition('__')
        if _t == 'bool':
            _dict[new_k] = _dict.pop_bool_param(k)

    return _dict

import pytest
from mock import patch, Mock, call
from nefertari.json_httpexceptions import (
    JHTTPBadRequest,
    JHTTPNotFound,
)

from .fixtures import (
    simple_model, id_model, story_model, person_model,
    tag_model, parent_model)
from nefertari_es import documents as docs


class TestBaseDocument(object):

    def test_comparison(self, simple_model):
        item1 = simple_model(name=None)
        item2 = simple_model(name=None)
        assert item1 != item2
        item2.name = '2'
        assert item1 != item2
        item1.name = '1'
        assert item1 != item2
        item1.name = '2'
        assert item1 == item2

    def test_hash(self, simple_model):
        items = set()
        item1 = simple_model(name='1')
        items.add(item1)
        assert item1 in items
        item2 = simple_model(name='asd')
        assert item2 not in items
        item2.name = '1'
        assert item2 in items

    def test_sync_id_field(self, id_model):
        item = id_model()
        assert item.id is None
        item._id = 123
        item._sync_id_field()
        assert item.id == '123'

    def test_setattr_readme_id(self, id_model):
        item = id_model()
        with pytest.raises(AttributeError) as ex:
            item.id = 123
        assert 'id is read-only' in str(ex.value)

    def test_getattr_id_none(self, id_model):
        item = id_model()
        assert item._id is None
        item.meta['id'] = 123
        assert item._id == 123

    @patch('nefertari_es.documents.BaseDocument._load_related')
    def test_getattr_load_rel(self, mock_load, story_model):
        story = story_model()
        story.author
        mock_load.assert_called_once_with('author')

    @patch('nefertari_es.documents.BaseDocument._load_related')
    def test_getattr_raw(self, mock_load, story_model):
        story = story_model(author=1)
        assert mock_load.call_count == 1
        assert story._getattr_raw('author') == 1
        assert mock_load.call_count == 1

    @patch('nefertari_es.documents.BaseDocument._load_related')
    def test_unload_related(self, mock_load, parent_model, person_model):
        parent = parent_model()
        parent.children = [person_model(name='123')]
        assert isinstance(parent.children[0], person_model)
        parent._unload_related('children')
        assert parent.children == ['123']

    @patch('nefertari_es.documents.BaseDocument._load_related')
    def test_unload_related_no_ids(self, mock_load, parent_model,
                                   person_model):
        parent = parent_model()
        person = person_model(name=None)
        parent._d_['children'] = [person]
        assert isinstance(parent.children[0], person_model)
        parent._unload_related('children')
        assert parent.children == [person]

    @patch('nefertari_es.documents.BaseDocument._load_related')
    def test_unload_related_no_curr_value(
            self, mock_load, parent_model, person_model):
        parent = parent_model()
        parent._d_['children'] = []
        parent._unload_related('children')
        assert parent.children == []

    def test_load_related(self, parent_model, person_model):
        parent = parent_model()
        parent.children = ['123']
        with patch.object(person_model, 'get_collection') as mock_get:
            mock_get.return_value = ['foo']
            parent._load_related('children')
            mock_get.assert_called_once_with(name=['123'])
            assert parent.children == ['foo']

    def test_load_related_no_items(self, parent_model, person_model):
        parent = parent_model()
        parent.children = ['123']
        with patch.object(person_model, 'get_collection') as mock_get:
            mock_get.return_value = []
            parent._load_related('children')
            mock_get.assert_called_once_with(name=['123'])
            assert parent.children == ['123']

    def test_load_related_no_curr_value(
            self, parent_model, person_model):
        parent = parent_model()
        parent.children = []
        with patch.object(person_model, 'get_collection') as mock_get:
            mock_get.return_value = ['foo']
            parent._load_related('children')
            assert not mock_get.called
            assert parent.children == []

    def test_save(self, person_model):
        person = person_model(name='foo')
        person._sync_id_field = Mock()
        person.save()
        person._sync_id_field.assert_called_once_with()

    def test_update(self, simple_model):
        item = simple_model(name='foo', price=123)
        assert item.name == 'foo'
        assert item.price == 123
        item.save = Mock()
        item.update({'name': 'bar', 'price': 321}, zoo=1)
        assert item.name == 'foo'
        assert item.price == 321
        item.save.assert_called_once_with(zoo=1)

    def test_to_dict(self, simple_model):
        item = simple_model(name='joe', price=42)
        assert item.to_dict() == {'name': 'joe', 'price': 42}
        assert item.to_dict(include_meta=True) == {
            '_source': {'name': 'joe', 'price': 42}, '_type': 'Item'}

    def test_to_dict_simple_request(self, simple_model):
        item = simple_model(name='joe', price=42)
        assert item.to_dict(request=True) == {
            'name': 'joe', 'price': 42,
            '_type': 'Item', '_pk': 'joe'}

    def test_to_dict_nest_depth_not_reached(
            self, person_model, tag_model, story_model):
        sking = person_model(name='Stephen King')
        novel = tag_model(name='novel')
        story = story_model(name='11/22/63', author=sking, tags=[novel])
        story._unload_related = Mock()
        story._load_related = Mock()
        story._nested_relationships = ['author', 'tags']
        data = story.to_dict(request=True, _depth=1)
        assert data == {
            '_pk': '11/22/63',
            '_type': 'Story',
            'author': {'_pk': 'Stephen King', '_type': 'Person', 'name': 'Stephen King'},
            'name': '11/22/63',
            'tags': [{'_pk': 'novel', '_type': 'Tag', 'name': 'novel'}]
        }
        assert not story._unload_related.called
        story._load_related.assert_has_calls([
            call('author'), call('tags')], any_order=True)
        assert sking._nesting_depth == 0
        assert sking._request
        assert novel._nesting_depth == 0
        assert novel._request

    def test_to_dict_nest_depth_reached(
            self, person_model, tag_model, story_model):
        sking = person_model(name='Stephen King')
        novel = tag_model(name='novel')
        story = story_model(name='11/22/63', author=sking, tags=[novel])
        story._load_related = Mock()
        story._nested_relationships = ['author', 'tags']
        data = story.to_dict(request=True, _depth=0)
        assert data == {
            '_pk': '11/22/63',
            '_type': 'Story',
            'author': 'Stephen King',
            'name': '11/22/63',
            'tags': ['novel']
        }
        assert not story._load_related.called
        assert sking._nesting_depth == 1
        assert sking._request is None
        assert novel._nesting_depth == 1
        assert novel._request is None

    def test_to_dict_nest_not_nested(
            self, person_model, tag_model, story_model):
        sking = person_model(name='Stephen King')
        novel = tag_model(name='novel')
        story = story_model(name='11/22/63', author=sking, tags=[novel])
        story._load_related = Mock()
        story._nested_relationships = ['tags']
        data = story.to_dict(request=True, _depth=1)
        assert data == {
            '_pk': '11/22/63',
            '_type': 'Story',
            'author': 'Stephen King',
            'name': '11/22/63',
            'tags': [{'_pk': 'novel', '_type': 'Tag', 'name': 'novel'}]
        }
        story._load_related.assert_has_calls([call('tags')])
        assert sking._nesting_depth == 1
        assert sking._request is None
        assert novel._nesting_depth == 0
        assert novel._request

    def test_to_dict_nest_no_request(
            self, person_model, tag_model, story_model):
        sking = person_model(name='Stephen King')
        novel = tag_model(name='novel')
        story = story_model(name='11/22/63', author=sking, tags=[novel])
        story._load_related = Mock()
        story._nested_relationships = ['author', 'tags']
        data = story.to_dict(_depth=1)
        assert data == {
            'author': 'Stephen King',
            'name': '11/22/63',
            'tags': ['novel']
        }
        assert not story._load_related.called
        assert sking._nesting_depth == 1
        assert sking._request is None
        assert novel._nesting_depth == 1
        assert novel._request is None

    def test_to_dict_nest_no_relations(
            self, person_model, tag_model, story_model):
        story = story_model(name='11/22/63', author=None, tags=[])
        story._load_related = Mock()
        story._nested_relationships = ['author', 'tags']
        data = story.to_dict(request=True, _depth=1)
        assert data == {
            '_pk': '11/22/63', '_type': 'Story', 'name': '11/22/63'}
        story._load_related.assert_has_calls([
            call('author'), call('tags')], any_order=True)

    def test_flatten_relationships(
            self, person_model, tag_model, story_model):
        sking = person_model(name='Stephen King')
        novel = tag_model(name='novel')
        params = {'name': '11/22/63', 'author': sking, 'tags': [novel]}
        flat = story_model._flatten_relationships(params)
        assert flat == {
            'name': '11/22/63',
            'author': 'Stephen King',
            'tags': ['novel']}

    def test_relationships_method(self, story_model):
        assert set(story_model._relationships()) == {'author', 'tags'}

    def test_pk_field(self, simple_model):
        field = simple_model._doc_type.mapping['name']
        field._primary_key = True
        assert simple_model.pk_field() == 'name'

    def test_pk_field_type(self, simple_model):
        from nefertari_es.fields import StringField
        field = simple_model._doc_type.mapping['name']
        field._primary_key = True
        assert simple_model.pk_field_type() is StringField

    def test_get_item_found(self, simple_model):
        simple_model.get_collection = Mock(return_value=['one', 'two'])
        item = simple_model.get_item(foo=1)
        simple_model.get_collection.assert_called_once_with(
            _limit=1, _item_request=True, foo=1)
        assert item == 'one'

    def test_get_item_not_found_not_raise(self, simple_model):
        simple_model.get_collection = Mock(return_value=[])
        item = simple_model.get_item(foo=1, _raise_on_empty=False)
        simple_model.get_collection.assert_called_once_with(
            _limit=1, _item_request=True, foo=1)
        assert item is None

    def test_get_item_not_found_raise(self, simple_model):
        simple_model.get_collection = Mock(return_value=[])
        with pytest.raises(JHTTPNotFound) as ex:
            simple_model.get_item(foo=1)
        assert 'resource not found' in str(ex.value)
        simple_model.get_collection.assert_called_once_with(
            _limit=1, _item_request=True, foo=1)

    @patch('nefertari_es.documents._bulk')
    def test_update_many(self, mock_bulk, simple_model):
        item = simple_model(name='first', price=2)
        simple_model._update_many([item], {'name': 'second'})
        mock_bulk.assert_called_once_with(
            [{'doc': {'name': 'second'}, '_type': 'Item'}],
            item.connection, op_type='update', request=None)

    @patch('nefertari_es.documents._bulk')
    def test_delete_many(self, mock_bulk, simple_model):
        item = simple_model(name='first', price=2)
        simple_model._delete_many([item])
        mock_bulk.assert_called_once_with(
            [{'_type': 'Item', '_source': {'price': 2, 'name': 'first'}}],
            item.connection, op_type='delete', request=None)

    def test_get_field_params(self, story_model):
        assert story_model.get_field_params('name') == {
            'primary_key': True}
        assert story_model.get_field_params('author') == {
            'backref_name': 'story',
            'document_type': 'Person',
            'uselist': False}

    def test_fields_to_query(self, simple_model):
        assert set(simple_model.fields_to_query()) == {
            '_id', 'name', 'price'}



class TestHelpers(object):
    @patch('nefertari_es.documents._validate_fields')
    def test_cleaned_query_params_strict(self, mock_val, simple_model):
        params = {
            'name': 'user12',
            'foobar': 'user12',
            '__id': 2,
            'price': '_all',
        }
        cleaned = docs._cleaned_query_params(simple_model, params, True)
        expected = {'name': 'user12', 'foobar': 'user12'}
        assert cleaned == expected
        mock_val.assert_called_once_with(simple_model, expected.keys())

    def test_cleaned_query_params_not_strict(self, simple_model):
        params = {
            'name': 'user12',
            'foobar': 'user12',
            '__id': 2,
            'price': '_all',
        }
        cleaned = docs._cleaned_query_params(simple_model, params, False)
        assert cleaned == {'name': 'user12'}

    def test_restructure_params(self, id_model):
        params = {'id': 'foo', 'name': 1}
        assert docs._restructure_params(id_model, params) == {
            '_id': ['foo'], 'name': [1]}

    def test_validate_fields_valid(self, simple_model):
        try:
            docs._validate_fields(simple_model, ['name', 'price'])
        except JHTTPBadRequest as ex:
            raise Exception('Unexpected error: {}'.format(str(ex)))

    def test_validate_fields_invalid(self, simple_model):
        with pytest.raises(JHTTPBadRequest) as ex:
            docs._validate_fields(simple_model, ['fofo', 'price'])
        assert 'object does not have fields: fofo' in str(ex.value)

    @patch('nefertari_es.documents.helpers')
    def test_bulk(self, mock_helpers):
        mock_helpers.bulk.return_value = (5, None)
        request = Mock()
        request.params.mixed.return_value = {'_refresh_index': 'true'}
        result = docs._bulk([{'id': 1}], 'foo', 'delete', request)
        mock_helpers.bulk.assert_called_once_with(
            client='foo',
            actions=[{'id': 1, '_op_type': 'delete'}])
        assert result == 5


@patch('nefertari_es.documents.BaseDocument.search')
class TestGetCollection(object):

    def test_q_search_fields_params(self, mock_search, simple_model):
        result = simple_model.get_collection(
            q='foo', _search_fields='name')
        mock_search.assert_called_once_with()
        mock_search().query.assert_called_once_with(
            'query_string', query='foo', fields=['name'])
        assert result == mock_search().query().execute().hits
        assert result._nefertari_meta == {
            'total': result.total,
            'start': None,
            'fields': None,
        }

    @patch('nefertari_es.documents.process_limit')
    def test_limit_param(self, mock_proc, mock_search, simple_model):
        mock_proc.return_value = (1, 2)
        result = simple_model.get_collection(_limit=20)
        mock_proc.assert_called_once_with(None, None, 20)
        mock_search.assert_called_once_with()
        mock_search().extra.assert_called_once_with(
            from_=1, size=2)
        assert result == mock_search().extra().execute().hits
        assert result._nefertari_meta == {
            'total': result.total,
            'start': 1,
            'fields': None,
        }

    @patch('nefertari_es.documents._validate_fields')
    @patch('nefertari_es.documents.process_fields')
    def test_fields_strict_param(
            self, mock_proc, mock_val, mock_search, simple_model):
        mock_proc.return_value = (['name'], ['price'])
        result = simple_model.get_collection(_fields='name,-price')
        mock_proc.assert_called_once_with('name,-price')
        mock_val.assert_called_once_with(simple_model, ['name', 'price'])
        mock_search.assert_called_once_with()
        mock_search().fields.assert_called_once_with(['name'])
        assert result == mock_search().fields().execute().hits
        assert result._nefertari_meta == {
            'total': result.total,
            'start': None,
            'fields': 'name,-price',
        }

    @patch('nefertari_es.documents._cleaned_query_params')
    def test_params_param(self, mock_clean, mock_search, simple_model):
        mock_clean.return_value = {'foo': 1}
        result = simple_model.get_collection(foo=2)
        mock_clean.assert_called_once_with(
            simple_model, {'foo': 2}, True)
        mock_search.assert_called_once_with()
        mock_search().filter.assert_called_once_with(
            'terms', foo=[1])
        assert result == mock_search().filter().execute().hits

    def test_count_param(self, mock_search, simple_model):
        result = simple_model.get_collection(_count=True)
        mock_search.assert_called_once_with()
        assert result == mock_search().count()

    def test_explain_param(self, mock_search, simple_model):
        result = simple_model.get_collection(q='foo', _explain=True)
        mock_search.assert_called_once_with()
        assert result == mock_search().query().to_dict()

    @patch('nefertari_es.documents._validate_fields')
    def test_sort_strict_param(self, mock_val, mock_search, simple_model):
        result = simple_model.get_collection(_sort='name,-price')
        mock_val.assert_called_once_with(simple_model, ['name', 'price'])
        mock_search.assert_called_once_with()
        mock_search().sort.assert_called_once_with(
            'name', '-price')
        assert result == mock_search().sort().execute().hits


class TestSyncRelatedMixin(object):
    def test_mixin_included_in_doc(self):
        assert docs.SyncRelatedMixin in docs.BaseDocument.__mro__

    def test_setattr(self, story_model):
        item = story_model()
        item._load_related = Mock()
        item._sync_related = Mock()
        item.author = 1
        item._load_related.assert_called_once_with('author')
        item._sync_related.assert_called_once_with(
            new_value=1, old_value=None, field_name='author')

    def test_sync_related_multiple_items(self, story_model):
        story = story_model(name='11/22/63')
        story._register_addition_hook = Mock()
        story._register_deletion_hook = Mock()
        story._sync_related([1, 2], [2, 3], 'tags')
        story._register_addition_hook.assert_called_once_with(
            1, 'stories')
        story._register_deletion_hook.assert_called_once_with(
            3, 'stories')

    def test_sync_related_one_item(self, story_model):
        story = story_model(name='11/22/63')
        story._register_addition_hook = Mock()
        story._register_deletion_hook = Mock()
        story._sync_related(1, 3, 'tags')
        story._register_addition_hook.assert_called_once_with(
            1, 'stories')
        story._register_deletion_hook.assert_called_once_with(
            3, 'stories')

    def test_sync_related_not_changed(self, story_model):
        story = story_model(name='11/22/63')
        story._register_addition_hook = Mock()
        story._register_deletion_hook = Mock()
        story._sync_related([1], [1], 'tags')
        assert not story._register_addition_hook.called
        assert not story._register_deletion_hook.called
        story._sync_related(1, 1, 'tags')
        assert not story._register_addition_hook.called
        assert not story._register_deletion_hook.called

    @patch('nefertari_es.documents.partial')
    def test_register_addition_hook(self, mock_partial, simple_model):
        obj = simple_model()
        assert len(obj._backref_hooks) == 0
        obj._register_addition_hook(1, 2)
        mock_partial.assert_called_once_with(
            simple_model._addition_hook,
            _item=1,
            _add_item=obj,
            _field_name=2)
        assert mock_partial() in obj._backref_hooks
        assert len(obj._backref_hooks) == 1

    @patch('nefertari_es.documents.partial')
    def test_register_deletion_hook(self, mock_partial, simple_model):
        obj = simple_model()
        assert len(obj._backref_hooks) == 0
        obj._register_deletion_hook(1, 2)
        mock_partial.assert_called_once_with(
            simple_model._deletion_hook,
            _item=1,
            _del_item=obj,
            _field_name=2)
        assert mock_partial() in obj._backref_hooks
        assert len(obj._backref_hooks) == 1

    @patch('nefertari_es.documents.BaseDocument._load_related')
    @patch('nefertari_es.documents.BaseDocument.update')
    def test_addition_hook_multi_changed(
            self, mock_upd, mock_load, story_model):
        story = story_model(name='foo', tags=[1, 2])
        docs.SyncRelatedMixin._addition_hook(story, 3, 'tags')
        story.update.assert_called_once_with({'tags': [1, 2, 3]})

    @patch('nefertari_es.documents.BaseDocument._load_related')
    @patch('nefertari_es.documents.BaseDocument.update')
    def test_addition_hook_multi_not_changed(
            self, mock_upd, mock_load, story_model):
        story = story_model(name='foo', tags=[1, 2])
        docs.SyncRelatedMixin._addition_hook(story, 1, 'tags')
        assert not story.update.called

    @patch('nefertari_es.documents.BaseDocument._load_related')
    @patch('nefertari_es.documents.BaseDocument.update')
    def test_addition_hook_single_changed(
            self, mock_upd, mock_load, story_model):
        story = story_model(name='foo', author=1)
        docs.SyncRelatedMixin._addition_hook(story, 3, 'author')
        story.update.assert_called_once_with({'author': 3})

    @patch('nefertari_es.documents.BaseDocument._load_related')
    @patch('nefertari_es.documents.BaseDocument.update')
    def test_addition_hook_single_not_changed(
            self, mock_upd, mock_load, story_model):
        story = story_model(name='foo', author=1)
        docs.SyncRelatedMixin._addition_hook(story, 1, 'author')
        assert not story.update.called

    @patch('nefertari_es.documents.BaseDocument._load_related')
    @patch('nefertari_es.documents.BaseDocument.update')
    def test_deletion_hook_multi_changed(
            self, mock_upd, mock_load, story_model):
        story = story_model(name='foo', tags=[1, 2])
        docs.SyncRelatedMixin._deletion_hook(story, 1, 'tags')
        story.update.assert_called_once_with({'tags': [2]})

    @patch('nefertari_es.documents.BaseDocument._load_related')
    @patch('nefertari_es.documents.BaseDocument.update')
    def test_deletion_hook_multi_not_changed(
            self, mock_upd, mock_load, story_model):
        story = story_model(name='foo', tags=[1, 2])
        docs.SyncRelatedMixin._deletion_hook(story, 3, 'tags')
        assert not story.update.called

    @patch('nefertari_es.documents.BaseDocument._load_related')
    @patch('nefertari_es.documents.BaseDocument.update')
    def test_deletion_hook_single_changed(
            self, mock_upd, mock_load, story_model):
        story = story_model(name='foo', author=1)
        docs.SyncRelatedMixin._deletion_hook(story, 1, 'author')
        story.update.assert_called_once_with({'author': None})

    @patch('nefertari_es.documents.BaseDocument._load_related')
    @patch('nefertari_es.documents.BaseDocument.update')
    def test_deletion_hook_single_not_changed(
            self, mock_upd, mock_load, story_model):
        story = story_model(name='foo', author=1)
        docs.SyncRelatedMixin._deletion_hook(story, 3, 'author')
        assert not story.update.called


@patch('nefertari_es.documents.DocType.save')
class TestRelationsSyncFunctional(object):
    def _test_data(self, person_model, tag_model, story_model):
        sking = person_model(name='Stephen King')
        novel = tag_model(name='novel')
        story = story_model(name='11/22/63')
        story.author = sking
        story.tags = [novel]
        with patch('nefertari_es.documents.DocType.save') as mock_save:
            story.save()
        return sking, novel, story

    def test_multifield_added_new_value(
            self, mock_save, person_model, tag_model, story_model):
        sking, novel, story = self._test_data(
            person_model, tag_model, story_model)
        fiction = tag_model(name='fiction')
        story.tags = [fiction, novel]
        assert fiction.stories == []
        story.save()
        assert len(fiction.stories) == 1
        assert story in fiction.stories

    def test_multifield_deleted_old_value(
            self, mock_save, person_model, tag_model, story_model):
        sking, novel, story = self._test_data(
            person_model, tag_model, story_model)
        story.tags = []
        assert len(novel.stories) == 1
        assert story in novel.stories
        story.save()
        assert novel.stories == []

    def test_singlefield_changed_value(
            self, mock_save, person_model, tag_model, story_model):
        sking, novel, story = self._test_data(
            person_model, tag_model, story_model)
        jdoe = person_model(name='John Doe')
        story.author = jdoe
        assert jdoe.story is None
        assert sking.story == story
        story.save()
        assert jdoe.story == story
        assert sking.story is None

    def test_singlefield_deleted_value(
            self, mock_save, person_model, tag_model, story_model):
        sking, novel, story = self._test_data(
            person_model, tag_model, story_model)
        story.author = None
        assert sking.story == story
        story.save()
        assert sking.story is None

    def test_one_to_many_changes_on_many_side(
            self, mock_save, person_model, parent_model):
        person1 = person_model(name='person1')
        person2 = person_model(name='person2')
        parent = parent_model(name='parent')
        assert parent.children == []
        person1.parent = parent
        person1.save()
        assert len(parent.children) == 1
        assert person1 in parent.children
        person2.parent = parent
        person2.save()
        assert len(parent.children) == 2
        assert person2 in parent.children
        assert person1 in parent.children
        person1.parent = None
        person1.save()
        assert len(parent.children) == 1
        assert person2 in parent.children

    def test_one_to_many_changes_on_one_side(
            self, mock_save, person_model, parent_model):
        person1 = person_model(name='person1')
        person2 = person_model(name='person2')
        parent = parent_model(name='parent')
        assert person1.parent is None
        assert person2.parent is None
        parent.children = [person1]
        parent.save()
        assert person1.parent == parent
        parent.children = [person2]
        parent.save()
        assert person1.parent is None
        assert person2.parent == parent
        parent.children = []
        parent.save()
        assert person1.parent is None
        assert person2.parent is None

    def test_sync_on_creation(
            self, mock_save, person_model, tag_model,
            story_model):
        sking = person_model(name='Stephen King')
        novel = tag_model(name='novel')
        story = story_model(name='11/22/63', author=sking, tags=[novel])
        assert sking.story is None
        assert novel.stories == []
        story.save()

        assert sking.story == story
        assert len(novel.stories) == 1
        assert story in novel.stories

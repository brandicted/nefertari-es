import datetime
from mock import Mock, patch

import pytest
from elasticsearch_dsl.exceptions import ValidationException
from elasticsearch_dsl.utils import AttrList

from nefertari_es import fields
from .fixtures import (
    id_model,
    story_model,
    tag_model,
    person_model,
    parent_model,
)


class TestFieldHelpers(object):

    def test_custom_mapping_mixin(self):
        class DummyBase(object):
            def to_dict(self):
                return {'foo': 1, 'bar': 2}

        class DummyField(fields.CustomMappingMixin, DummyBase):
            _custom_mapping = {'foo': 3, 'zoo': 4}

        obj = DummyField()
        assert obj.to_dict() == {'foo': 3, 'bar': 2, 'zoo': 4}


class TestFields(object):
    def test_basefieldmixin(self):
        class DummyBase(object):
            def __init__(self, required=False):
                self.required = required

        class DummyField(fields.BaseFieldMixin, DummyBase):
            pass
        field = DummyField(primary_key=True)
        assert field._primary_key
        assert field.required

    def test_drop_invalid_kwargs(self):
        class DummyBase(object):
            pass

        class DummyField(fields.BaseFieldMixin, DummyBase):
            _valid_kwargs = ('foo',)

        field = DummyField()
        assert field.drop_invalid_kwargs({'foo': 1, 'bar': 2}) == {
            'foo': 1}

    def test_idfield(self):
        field = fields.IdField()
        assert field._primary_key
        assert not field._required

    def test_idfield_empty(self):
        field = fields.IdField()
        assert field._empty() is None

    def test_intervalfield_to_python(self):
        from datetime import timedelta
        field = fields.IntervalField()
        val = field._to_python(600)
        assert isinstance(val, timedelta)
        assert val.total_seconds() == 600


class TestDateTimeField(object):

    def test_to_python_no_data(self):
        obj = fields.DateTimeField()
        assert obj._to_python({}) is None
        assert obj._to_python([]) is None
        assert obj._to_python(None) is None
        assert obj._to_python('') is None

    def test_to_python_datetime(self):
        obj = fields.DateTimeField()
        date = datetime.datetime.now()
        assert obj._to_python(date) is date

    def test_to_python_string_parse(self):
        obj = fields.DateTimeField()
        expected = datetime.datetime(year=2000, month=11, day=12)
        assert obj._to_python('2000-11-12') == expected

    def test_to_python_parse_failed(self):
        obj = fields.DateTimeField()
        with pytest.raises(ValidationException) as ex:
            obj._to_python('asd')
        expected = 'Could not parse datetime from the value'
        assert expected in str(ex.value)


class TestTimeField(object):

    def test_to_python_no_data(self):
        obj = fields.TimeField()
        assert obj._to_python({}) is None
        assert obj._to_python([]) is None
        assert obj._to_python(None) is None
        assert obj._to_python('') is None

    def test_to_python_time(self):
        obj = fields.TimeField()
        time = datetime.datetime.now().time()
        assert obj._to_python(time) is time

    def test_to_python_datetime(self):
        obj = fields.TimeField()
        date = datetime.datetime.now()
        assert obj._to_python(date) == date.time()

    def test_to_python_string_parse(self):
        obj = fields.TimeField()
        expected = datetime.time(17, 40)
        assert obj._to_python('2000-11-12 17:40') == expected

    def test_to_python_parse_failed(self):
        obj = fields.TimeField()
        with pytest.raises(ValidationException) as ex:
            obj._to_python('asd')
        expected = 'Could not parse time from the value'
        assert expected in str(ex.value)


class TestRelationshipField(object):

    def test_to_dict_nested(self, story_model,
                            person_model, tag_model):
        story_model._nested_relationships = ('author', 'tags')
        req = Mock()
        s = story_model(name='Moby Dick')
        assert s.to_dict(request=req) == {
            'name': 'Moby Dick',
            '_pk': 'Moby Dick',
            '_type': 'Story'
        }
        s.author = person_model(name='Melville')
        assert s.to_dict(request=req)['author'] == {
            '_pk': 'Melville', '_type': 'Person', 'name': 'Melville'}
        s.tags = [tag_model(name='whaling'), tag_model(name='literature')]
        assert s.to_dict(request=req)['tags'] == [
            {'_pk': 'whaling', '_type': 'Tag', 'name': 'whaling'},
            {'_pk': 'literature', '_type': 'Tag', 'name': 'literature'}]

    def test_to_dict_not_nested(self, story_model,
                                person_model, tag_model):
        req = Mock()
        s = story_model(name='Moby Dick')
        assert s.to_dict(request=req) == {
            'name': 'Moby Dick',
            '_pk': 'Moby Dick',
            '_type': 'Story'
        }
        s.author = person_model(name='Melville')
        assert s.to_dict(request=req)['author'] == 'Melville'
        t1 = tag_model(name='whaling')
        t2 = tag_model(name='literature')
        s.tags = [t1, t2]
        assert s.to_dict(request=req)['tags'] == ['whaling', 'literature']

    def test_to_dict_es(self, story_model, person_model, tag_model):
        s = story_model(name='Moby Dick')
        assert s.to_dict() == {'name': 'Moby Dick'}
        a = person_model(name='Melville')
        s.author = a
        assert s.to_dict()['author'] == 'Melville'
        t1 = tag_model(name='whaling')
        t2 = tag_model(name='literature')
        s.tags = [t1, t2]
        assert s.to_dict()['tags'] == ['whaling', 'literature']


class TestReferenceField(object):
    def _get_field(self):
        return fields.ReferenceField(
            'Foo', uselist=False, backref_name='zoo')

    def test_init(self):
        field = self._get_field()
        assert field._doc_class_name == 'Foo'
        assert not field._multi
        assert field._backref_kwargs == {'name': 'zoo'}

    def test_drop_invalid_kwargs(self):
        field = self._get_field()
        kwargs = {'required': True, 'backref_required': True, 'Foo': 1}
        assert field.drop_invalid_kwargs(kwargs) == {
            'required': True, 'backref_required': True}

    @patch('nefertari_es.meta.get_document_cls')
    def test_doc_class(self, mock_get):
        field = self._get_field()
        assert field._doc_class_name == 'Foo'
        klass = field._doc_class
        mock_get.assert_called_once_with('Foo')
        assert klass == mock_get()

    def test_empty_not_required(self):
        field = self._get_field()
        field._required = False
        field._multi = True
        val = field.empty()
        assert isinstance(val, AttrList)
        assert len(val) == 0

        field._multi = False
        assert field.empty() is None

    @patch('nefertari_es.meta.get_document_cls')
    def test_clean(self, mock_get):
        mock_get.return_value = dict
        field = self._get_field()
        field._doc_class
        val = 'asdasdasdasd'
        assert field.clean(val) is val


class TestIdField(object):

    def test_read_only(self, id_model):
        d = id_model()
        with pytest.raises(AttributeError) as e:
            d.id = 'fail'
        assert str(e.value) == 'id is read-only'

    def test_populate_id_field(self, id_model):
        d = id_model()
        assert d.id is None

        # simulate a save
        d._id = 'ID'
        d._populate_id_field()

        assert d.id == d._id

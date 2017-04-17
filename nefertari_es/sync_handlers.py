from nefertari.engine import sync_events


def includeme(config):
    add_sub = config.add_subscriber
    add_sub(handle_item_created, sync_events.ItemCreated)
    add_sub(handle_item_updated, sync_events.ItemUpdated)
    add_sub(handle_item_deleted, sync_events.ItemDeleted)
    add_sub(handle_bulk_updated, sync_events.BulkUpdated)
    add_sub(handle_bulk_deleted, sync_events.BulkDeleted)


def handle_item_created(event):
    item = event.item
    es_model = item.__class__._secondary
    item_data = item.to_dict(_depth=0)
    item_data.pop('_type', None)
    item_data.pop('_version', None)
    item_data.pop('_pk', None)
    es_model(**item_data).save()


def handle_item_updated(event):
    item = event.item
    _update_item(item)


def _update_item(item):
    es_model = item.__class__._secondary
    item_data = item.to_dict(_depth=0)
    item_data.pop('_type', None)
    item_data.pop('_version', None)
    item_pk = item_data.pop('_pk', None)
    pk_field = es_model.pk_field()
    es_item = es_model.get_item(**{pk_field: item_pk})
    es_item.update(item_data)


def handle_item_deleted(event):
    item = event.item
    es_model = item.__class__._secondary
    pk_field = es_model.pk_field()
    item_pk = getattr(item, pk_field)
    es_item = es_model.get_item(**{pk_field: item_pk})
    es_item.delete()


def _get_es_model(event):
    items = event.items or []
    try:
        return items[0].__class__._secondary
    except IndexError:
        return None


def _get_es_items(event):
    items = event.items or []
    es_model = _get_es_model(event)
    if es_model is None or not items:
        return
    pk_field = es_model.pk_field()
    item_ids = [getattr(item, pk_field) for item in items]
    return es_model.get_collection(**{pk_field: item_ids})


def handle_bulk_updated(event):
    es_model = _get_es_model(event)
    es_items = _get_es_items(event)
    items = event.items or []
    if not (es_model is not None and es_items and items):
        return
    pk_field = es_model.pk_field()
    items = {str(getattr(item, pk_field)): item for item in items}
    for es_item in es_items:
        es_pk = str(getattr(es_item, pk_field))
        db_item = items[es_pk]
        db_item_data = db_item.to_dict(_depth=0)
        db_item_data.pop('_type', None)
        db_item_data.pop('_version', None)
        db_item_data.pop('_pk', None)
        es_item._update(db_item_data)
    es_model._index_many(es_items, request=event.request)


def handle_bulk_deleted(event):
    es_model = _get_es_model(event)
    es_items = _get_es_items(event)
    if es_model is not None and es_items:
        es_model._delete_many(es_items, request=event.request)

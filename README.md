# Nefertari-Elasticsearch

Backend and search engine for Nefertari


Next tasks:

- Aggregations

- Multi-collection requests

- Rework es.py script in nefertari to work with nefertari-es (indexing
  all documents and missing documents)

- Update Ramses to work with multiple engines properly. ramses-example
  should work with nefertari-es and multiple engines.

- Docstrings

- Delete not used engines code related to ES (e.g. `get_es_mapping`)


Advanced tasks:

- Unique constraint on PK fields?

- Make nefertari-es work with token auth

- Make nefertari-es work wirh nefertari-guards

- Caching of loaded ES documents

- Make relationships sync work on _update_many/_delete_many

- Implement ondelete/onupdate hooks for relationships

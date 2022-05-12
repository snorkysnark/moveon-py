# Moveon API wrapper

Usage: see [update_contacts.ipynb](update_contacts.ipynb)

# Remapping contact ids
```bash
usage: update_contacts.py [-h] [-c CERT] [-k KEY] [--url URL] [--retry-time RETRY_TIME]
                          [-l LOG] [-v LOGLEVEL]
                          map_tsv

Remap institution_id of contacts

positional arguments:
  map_tsv               Tab-delimited csv with fields 'Institution: ID' and 'Institution: ID
                        target'

options:
  -h, --help            show this help message and exit
  -c CERT, --cert CERT  Path to ssl certificate
  -k KEY, --key KEY     Path to certificate key
  --url URL             MoveOn API url
  --retry-time RETRY_TIME
                        Delay between retrying requests
  -l LOG, --log LOG     Log file path
  -v LOGLEVEL, --loglevel LOGLEVEL
                        Log level
```

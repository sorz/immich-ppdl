# immich-ppdl

Script to batch download files from Immich with arbitrary search filters.

Features:

- Multithread downloading
- Arbitrary search filters
- Checksum validation

This is a third-party tool and not affiliated to the Immich project.

## Usage

### API key

To generate a API key, go to Immich / Account Settings / API Keys / New API Key

Required permission:

- `asset.read`
- `asset.download`

### Run script

[uv](https://github.com/astral-sh/uv) is recommended way to run this script.
It manages Python version and all dependencies for you.

```bash
uv run immich-ppdl.py --help
```

If you use other tool or Python directly, make sure `requests` and
`pydantic-settings` are avaliable.

#### Passing options

Options are pass by CLI arguments or as environment variables, or both.
For example,

```bash
uv run immich-ppdl.py \
  --immich_api_url "https://myserver/api" \
  --immmich_api_key "abcdEFGH1234" \
  --save_to /path/to/save
```

is the same as

```bash
export IMMICH_API_URL="https://myserver/api"
export IMMICH_API_KEY="abcdEFGH1234"
uv run immich-ppdl.py --save_to /path/to/save
```

<details>
<summary>Pass API key as file</summary>

Options are also read from `${CREDENTIALS_DIRECTORY}/option_name` files.

So if you set `LoadCredential=immmich_api_key:/etc/immich-api-key` on
systemd service, it will automatically read the API key from that file.

</details>

### Filters

By default, the script downloads all files (archive/hidden/locked excluded).
You can set filters to limit the range.

- `person_ids`: search specific persons (faces)
- `after`: files created after that time
- `last_days`: convenient way to set `after` to `today - last_days`

More can be set via `filters` passing directly to
[the search API](https://api.immich.app/endpoints/search/searchAssets).

For example:

```bash
uv run immich-ppdl.py \
  --person_ids 1111-aaa-bbb --person_ids 2222-xxx-yyy \
  --filters '{ "model": "Pixel 10", "isFavorite": true, "type": "IMAGE" }'
```

See Immich API docs on
[/search/metadata](https://api.immich.app/endpoints/search/searchAssets)
for a complete filter options.

### Output directory

Files are written to `{save_to}/YYYY/MM/DD/OriginalFileName`.
Currently it's unconfigurable.

Folders will be created, download will be skiped if same-name file exist.

## Known issues

- Output path cannot be configured with options
- If multiple files with the same original file name taken on the same day,
  only one will be download
- If the program exits abnormally, half-downloaded files may remain.
  After restarting, it will not try to re-download these corrupted files.

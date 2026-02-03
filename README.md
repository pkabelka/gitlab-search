# CLI GitLab search

Search for content across GitLab repositories from command line.

**WHY?**

Because GitLab can search globally only with Zoekt search engine enabled.

## Features

- Search across whole groups, subgroups or specific projects
- Boolean expression syntax similar to `find` command
- Search across different GitLab scopes: code, files, issues, merge requests, commits, ...
- Filter results by file name, extension or path
- Exclude specific subgroups or projects from search

## Requirements

- Python 3.13+
- No external dependencies

## Installation

```sh
git clone https://github.com/pkabelka/gitlab-search.git
cd gitlab-search
uv tool install .
```

Or you can use the tool directly after cloning:

```sh
uv run --project <clone_parent_directory>/gitlab-search gitlab-search
```

## Configuration

Create a personal access token with scopes:

- `read_api` for the code search
- `read_user` for searching across your own or other users projects
- `read_repository` for `files` search scope

The program tries to load the access token in this order:
- `--token '<YOUR_GITLAB_ACCESS_TOKEN>'` or `--token-file PATH`
- `GITLAB_SEARCH_TOKEN` environment variable

You can use `--setup` to store custom API URL, API certificate validation and
maximum number of concurrent requests. If you omit any of these, the default
values will be used or you can provide them with each search. By default the
configuration will be created in the current working directory and can be
changed with `-C` or `--config`.

```sh
gitlab-search --setup --api-url https://gitlab.your-domain.com/api/v4 --max-requests 10
```

The configuration file `.gitlab-search-config.json` is searched in current
directory, `XDG_CONFIG_HOME` environment variable, `~/.config` and `/etc`.

You can override configuration file with `--config PATH`.

## Usage

Basic usage to search all groups the user is member of:

```sh
gitlab-search -q "search text"
# enable recursive search
gitlab-search -r -q "search text"
```

Search in specific group:

```sh
gitlab-search -g somegroup -q "search text"
```

Exclude a specific project in a subgroup:

```sh
gitlab-search -g group ! -p group/subgroup/excluded-project -q "search text"
```

Show results if all queries are found in the same files:

```sh
gitlab-search -q "search text" -q "another text in same file"
gitlab-search -q "search text" -a -q "another text in same file"
```

Exclude file result if it contains some search text:

```sh
gitlab-search -q "search text" ! -q "excluded text in same file"
gitlab-search -q "search text" -a ! -q "excluded text in same file"
```

Find results containing either text1 or text2:

```sh
gitlab-search -q text1 -o -q text2
```

The GitLab API also searches filenames when providing the search text but you
can also search only by filenames using `-s files` which uses GitLab tree API.

```sh
gitlab-search -s files -q Makefile
```

Predicates are also supported for searching files:

```sh
gitlab-search -s files -q Makefile -o -q main.c
```

You can also filter results regardless of scope by filename, extension and
path:

```sh
gitlab-search -q main -P "src/*" ! -e .h
```

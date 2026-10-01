# Vendored front-end libraries

Bundled locally so the web UI makes no third-party network requests.

| Library   | Version | License                | Source                                   |
|-----------|---------|------------------------|------------------------------------------|
| marked    | 12.0.2  | MIT                    | https://github.com/markedjs/marked       |
| DOMPurify | 3.4.16  | MPL-2.0 OR Apache-2.0  | https://github.com/cure53/DOMPurify      |

Both files are unmodified `dist` builds from the official npm packages
(`marked/marked.min.js`, `dompurify/dist/purify.min.js`). To update, replace
them with the matching files from a newer npm release and update this table.

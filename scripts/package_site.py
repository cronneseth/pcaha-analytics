"""Wrap site/index.html in a full HTML document for static hosting (Netlify).

site/index.html is written as page content only, so the same file can be
previewed as a Claude artifact. This writes public/ with the full document
and the data files.
Usage: python package_site.py <site dir> <out dir>
"""
import os
import shutil
import sys

site, out = sys.argv[1], sys.argv[2]
shutil.rmtree(out, ignore_errors=True)
shutil.copytree(site, out)
with open(os.path.join(site, 'index.html')) as f:
    body = f.read()
head, sep, rest = body.partition('</style>')
doc = (
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
    'body{margin:0}[hidden]{display:none!important}img{max-width:100%}</style>\n'
    + head + sep + '\n</head>\n<body>\n' + rest + '\n</body>\n</html>\n'
)
with open(os.path.join(out, 'index.html'), 'w') as f:
    f.write(doc)
print('packaged', out)

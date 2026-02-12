from __future__ import annotations

import argparse
import logging
import re

import requests

from .config import load_config
from .logging import configure_logging
from .mediawiki import MediaWikiClient

log = logging.getLogger("bot.update_translation_status_ui")

TEMPLATE_TITLE = "Template:Translation_status"
COMMON_JS_TITLE = "MediaWiki:Common.js"
JS_START = "// DR_TRANSLATION_STATUS_BANNER_START"
JS_END = "// DR_TRANSLATION_STATUS_BANNER_END"

TEMPLATE_TEXT = """<includeonly><!-- Translation_status: status={{{status|machine}}} --></includeonly><noinclude>
Template used by bot-managed translated pages.

Parameters:
* status = machine|reviewed|outdated

This template intentionally renders no visible content.
</noinclude>
"""

COMMON_JS_BLOCK = f"""{JS_START}
( function () {{
  if ( mw.config.get( 'wgNamespaceNumber' ) !== 0 ) {{
    return;
  }}
  var pageName = mw.config.get( 'wgPageName' ) || '';
  var m = pageName.match( /\\/([a-z]{{2,3}}(?:-[a-z0-9]+)?)$/i );
  if ( !m ) {{
    return;
  }}
  var lang = m[1];
  var sourcePage = pageName.replace( /\\/[a-z]{{2,3}}(?:-[a-z0-9]+)?$/i, '' );
  var api = new mw.Api();

  function parseStatusFromWikitext( text ) {{
    var re = /\\{{\\{{\\s*Translation_status\\s*\\|([^}}]+)\\}}/i;
    var mm = text.match( re );
    if ( !mm ) {{
      return null;
    }}
    var params = {{}};
    mm[1].split( '|' ).forEach( function ( part ) {{
      var idx = part.indexOf( '=' );
      if ( idx === -1 ) {{
        return;
      }}
      var k = part.slice( 0, idx ).trim();
      var v = part.slice( idx + 1 ).trim();
      params[k] = v;
    }} );
    return params.status || null;
  }}

  function renderBanner( status ) {{
    status = status || 'machine';
    var textByStatus = {{
      machine: 'Machine translation. Help review this page.',
      reviewed: 'Human reviewed translation.',
      outdated: 'Translation is outdated compared to the English source. Update needed.'
    }};
    var text = textByStatus[status] || textByStatus.machine;
    var editUrl = mw.util.getUrl( pageName, {{ action: 'edit' }} );
    var sourceUrl = mw.util.getUrl( sourcePage );

    var banner = document.createElement( 'div' );
    banner.className = 'dr-translation-status dr-translation-status-' + status;
    banner.style.cssText = 'border:1px solid #c8ccd1;padding:10px 12px;margin:8px 0;background:#f8f9fa;';
    banner.innerHTML =
      '<strong>' + mw.html.escape( text ) + '</strong>' +
      ' <a href=\"' + editUrl + '\">Edit</a>' +
      ' · <a href=\"' + sourceUrl + '\">Source</a>';

    var content = document.getElementById( 'mw-content-text' );
    if ( content ) {{
      content.parentNode.insertBefore( banner, content );
    }}
  }}

  api.get( {{
    action: 'query',
    prop: 'pageprops|revisions',
    rvprop: 'content',
    rvslots: 'main',
    titles: pageName
  }} ).done( function ( data ) {{
    var pages = data && data.query && data.query.pages;
    if ( !pages ) {{
      return;
    }}
    var page = pages[Object.keys( pages )[0]];
    var status = page.pageprops && page.pageprops.dr_translation_status;
    if ( !status ) {{
      var rev = page.revisions && page.revisions[0];
      var text = rev && rev.slots && rev.slots.main && rev.slots.main.content || '';
      status = parseStatusFromWikitext( text ) || 'machine';
    }}
    renderBanner( status );
  }} );
}} )();
{JS_END}
"""


def _upsert_common_js(existing: str) -> str:
    pattern = re.compile(
        rf"{re.escape(JS_START)}.*?{re.escape(JS_END)}\n?",
        re.DOTALL,
    )
    if pattern.search(existing):
        return pattern.sub(COMMON_JS_BLOCK + "\n", existing)
    base = existing.rstrip()
    if base:
        return base + "\n\n" + COMMON_JS_BLOCK + "\n"
    return COMMON_JS_BLOCK + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-only", action="store_true")
    parser.add_argument("--js-only", action="store_true")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    if args.template_only and args.js_only:
        raise SystemExit("--template-only and --js-only are mutually exclusive")

    session = requests.Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    if not args.js_only:
        client.edit(
            TEMPLATE_TITLE,
            TEMPLATE_TEXT,
            "Bot: install Translation_status template",
            bot=True,
        )
        log.info("edited %s", TEMPLATE_TITLE)

    if not args.template_only:
        existing = ""
        try:
            existing, _, _ = client.get_page_wikitext(COMMON_JS_TITLE)
        except Exception:
            existing = ""
        updated = _upsert_common_js(existing)
        client.edit(
            COMMON_JS_TITLE,
            updated,
            "Bot: install translation status banner script",
            bot=True,
        )
        log.info("edited %s", COMMON_JS_TITLE)


if __name__ == "__main__":
    main()

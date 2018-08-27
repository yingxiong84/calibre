#!/usr/bin/env python2
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from __future__ import absolute_import, division, print_function, unicode_literals

from PyQt5.Qt import QApplication, QBuffer, QByteArray
from PyQt5.QtWebEngineCore import QWebEngineUrlSchemeHandler
from PyQt5.QtWebEngineWidgets import (
    QWebEnginePage, QWebEngineProfile, QWebEngineScript
)

from calibre import prints
from calibre.constants import (
    FAKE_HOST, FAKE_PROTOCOL, __version__, is_running_from_develop
)
from calibre.gui2 import open_url
from calibre.gui2.webengine import (
    Bridge, RestartingWebEngineView, create_script, from_js, insert_scripts,
    secure_webengine, to_js
)

try:
    from PyQt5 import sip
except ImportError:
    import sip

# Override network access to load data from the book {{{


def get_data(name):
    raise NotImplementedError('TODO: implement this')


class UrlSchemeHandler(QWebEngineUrlSchemeHandler):

    def __init__(self, parent=None):
        QWebEngineUrlSchemeHandler.__init__(self, parent)

    def requestStarted(self, rq):
        if bytes(rq.requestMethod()) != b'GET':
            rq.fail(rq.RequestDenied)
            return
        url = rq.requestUrl()
        if url.host() != FAKE_HOST or url.scheme() != FAKE_PROTOCOL:
            rq.fail(rq.UrlNotFound)
            return
        name = url.path()[1:]
        try:
            data, mime_type = get_data(name)
            if data is None:
                rq.fail(rq.UrlNotFound)
                return
            if isinstance(data, type('')):
                data = data.encode('utf-8')
            mime_type = {
                # Prevent warning in console about mimetype of fonts
                'application/vnd.ms-opentype':'application/x-font-ttf',
                'application/x-font-truetype':'application/x-font-ttf',
                'application/font-sfnt': 'application/x-font-ttf',
            }.get(mime_type, mime_type)
            self.send_reply(rq, mime_type, data)
        except Exception:
            import traceback
            traceback.print_exc()
            rq.fail(rq.RequestFailed)

    def send_reply(self, rq, mime_type, data):
        if sip.isdeleted(rq):
            return
        buf = QBuffer(parent=rq)
        buf.open(QBuffer.WriteOnly)
        # we have to copy data into buf as it will be garbage
        # collected by python
        buf.write(data)
        buf.seek(0)
        buf.close()
        buf.aboutToClose.connect(buf.deleteLater)
        rq.reply(mime_type.encode('ascii'), buf)

# }}}


def create_profile():
    ans = getattr(create_profile, 'ans', None)
    if ans is None:
        ans = QWebEngineProfile(QApplication.instance())
        ua = 'calibre-viewer ' + __version__
        ans.setHttpUserAgent(ua)
        if is_running_from_develop:
            from calibre.utils.rapydscript import compile_editor
            compile_editor()
        js = P('editor.js', data=True, allow_user_override=False)
        cparser = P('csscolorparser.js', data=True, allow_user_override=False)

        insert_scripts(ans,
            create_script('csscolorparser.js', cparser),
            create_script('editor.js', js),
        )
        url_handler = UrlSchemeHandler(ans)
        ans.installUrlSchemeHandler(QByteArray(FAKE_PROTOCOL.encode('ascii')), url_handler)
        s = ans.settings()
        s.setDefaultTextEncoding('utf-8')
        s.setAttribute(s.FullScreenSupportEnabled, False)
        s.setAttribute(s.LinksIncludedInFocusChain, False)
        create_profile.ans = ans
    return ans


class ViewerBridge(Bridge):

    request_sync = from_js(object, object, object)
    request_split = from_js(object, object)
    live_css_data = from_js(object)

    go_to_sourceline_address = to_js()
    go_to_anchor = to_js()
    set_split_mode = to_js()
    live_css = to_js()


class WebPage(QWebEnginePage):

    def __init__(self, parent):
        QWebEnginePage.__init__(self, create_profile(), parent)
        secure_webengine(self, for_viewer=True)
        self.bridge = ViewerBridge(self)

    def javaScriptConsoleMessage(self, level, msg, linenumber, source_id):
        prints('%s:%s: %s' % (source_id, linenumber, msg))

    def acceptNavigationRequest(self, url, req_type, is_main_frame):
        if req_type == self.NavigationTypeReload:
            return True
        if url.scheme() in (FAKE_PROTOCOL, 'data'):
            return True
        open_url(url)
        return False

    def go_to_anchor(self, anchor):
        self.bridge.go_to_anchor.emit(anchor or '')

    def runjs(self, src, callback=None):
        if callback is None:
            self.runJavaScript(src, QWebEngineScript.ApplicationWorld)
        else:
            self.runJavaScript(src, QWebEngineScript.ApplicationWorld, callback)


class WebView(RestartingWebEngineView):

    def __init__(self, parent=None):
        RestartingWebEngineView.__init__(self, parent)
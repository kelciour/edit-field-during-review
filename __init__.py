# -*- coding: utf-8 -*-

"""
Anki Add-on: Edit Field During Review

Edit text in a field during review without opening the edit window

Copyright: (c) 2019-2020 Nickolay Nonard <kelciour@gmail.com>
"""

from anki import hooks
from anki.template import TemplateRenderContext
from anki.utils import htmlToTextLine
from aqt.reviewer import Reviewer
from aqt import mw, gui_hooks
from aqt.utils import tooltip

import re
import unicodedata
import urllib.parse


try:
    from anki.rsbackend import NotFoundError # Anki 2.1.28+
except:
    class NotFoundError(Exception):
        pass

# https://github.com/ankitects/anki/blob/2.1.15/anki/template/template.py#L7
clozeReg = r"(?si)\{\{(c)\d+::(.*?)(::(.*?))?\}\}"

# https://github.com/ankitects/anki/blob/2.1.15/anki/latex.py#L21-L25
latexRegexps = {
    "standard": re.compile(r"\[latex\](.+?)\[/latex\]", re.DOTALL | re.IGNORECASE),
    "expression": re.compile(r"\[\$\](.+?)\[/\$\]", re.DOTALL | re.IGNORECASE),
    "math": re.compile(r"\[\$\$\](.+?)\[/\$\$\]", re.DOTALL | re.IGNORECASE),
}

mathJaxReg = r"(?si)(\\[\[\(])(.*?)(\\[\]\)])"

def safe_to_edit(text):
    if '[sound:' in text:
        return False
    if re.search(clozeReg, text):
        return False
    if re.search(mathJaxReg, text):
        return False
    if any(re.search(regex, text) for regex in latexRegexps.values()):
        return False
    return True

def on_edit_filter(text, field, filter, context: TemplateRenderContext):
    if filter != "edit":
        return text

    if not safe_to_edit(text):
        return text

    config = mw.addonManager.getConfig(__name__)
    card = context.card()
    nid = card.nid if card is not None else ""
    text = """<%s contenteditable="true" data-field="%s" data-nid="%s">%s</%s>""" % (config['tag'], field, nid, text, config['tag'])
    text += """<script>"""
    text += """
            $("[contenteditable=true][data-field='%s']").blur(function() {
                pycmd("ankisave#" + $(this).data("field") + "#" + $(this).data("nid") + "#" + $(this).html());
            });
        """ % field
    if config['tag'] == "span":
        text += """
            $("[contenteditable=true][data-field='%s']").keydown(function(evt) {
                if (evt.keyCode == 8) {
                    evt.stopPropagation();
                }
            });
        """ % field
    text += """
            $("[contenteditable=true][data-field='%s']").focus(function() {
                pycmd("ankisave!speedfocus#");
            });
        """ % field
    text += """</script>"""
    return text

hooks.field_filter.append(on_edit_filter)

def mungeHTML(txt):
    return "" if txt in ("<br>", "<div><br></div>") else txt

def saveField(note, fld, val):
    if fld == "Tags":
        tagsTxt = unicodedata.normalize("NFC", htmlToTextLine(val))
        txt = mw.col.tags.canonify(mw.col.tags.split(tagsTxt))
        field = note.tags
    else:
        # https://github.com/dae/anki/blob/47eab46f05c8cc169393c785f4c3f49cf1d7cca8/aqt/editor.py#L257-L263
        txt = urllib.parse.unquote(val)
        txt = unicodedata.normalize("NFC", txt)
        txt = mungeHTML(txt)
        txt = txt.replace("\x00", "")
        txt = mw.col.media.escapeImages(txt, unescape=True)
        field = note[fld]
    if field == txt:
        return
    config = mw.addonManager.getConfig(__name__)
    if config['undo']:
        mw.checkpoint("Edit Field")
    if fld == "Tags":
        note.tags = txt
    else:
        note[fld] = txt
    note.flush()

def on_js_message(handled, url, context):
    if not isinstance(context, Reviewer):
        return handled

    if url.startswith("ankisave#"):
        fld, nid, val = url.replace("ankisave#", "").split("#", 2)
        nid = int(nid)
        card = context.card
        note = card.note()
        config = mw.addonManager.getConfig(__name__)
        if config['debug']:
            assert nid == note.id, "{} == {}".format(nid, note.id)
        try:
            # make sure note is not deleted
            note2 = mw.col.getNote(nid)
        except NotFoundError:
            return True, None
        except TypeError as e:
            # NotFoundError if Anki < 2.1.28
            if str(e) == "cannot unpack non-iterable NoneType object":
                return True, None
            raise(e)
        # we need to reuse context.card.note() if nid == note.id
        # as changes will be lost once we open the editor window
        if nid != note.id:
            note = note2
        saveField(note, fld, val)
        card.q(reload=True)
        return True, None
    elif url.startswith("ankisave!speedfocus#"):
        mw.reviewer.bottom.web.eval("""
            clearTimeout(autoAnswerTimeout);
            clearTimeout(autoAlertTimeout);
            clearTimeout(autoAgainTimeout);
        """)
        return True, None
    return handled

gui_hooks.webview_did_receive_js_message.append(on_js_message)

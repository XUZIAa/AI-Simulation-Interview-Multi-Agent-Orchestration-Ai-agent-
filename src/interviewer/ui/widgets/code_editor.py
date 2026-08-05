from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextFormat,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from ..theme import MONO_FAMILY, Color

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "python": (
        "def", "class", "return", "if", "elif", "else", "for", "while", "in", "not", "and", "or",
        "import", "from", "as", "with", "try", "except", "finally", "raise", "lambda", "yield",
        "async", "await", "None", "True", "False", "self", "pass", "break", "continue", "global",
    ),
    "javascript": (
        "function", "const", "let", "var", "return", "if", "else", "for", "while", "do", "switch",
        "case", "break", "continue", "class", "extends", "new", "this", "typeof", "instanceof",
        "try", "catch", "finally", "throw", "async", "await", "null", "undefined", "true", "false",
    ),
    "typescript": (
        "function", "const", "let", "var", "return", "if", "else", "for", "while", "class", "interface",
        "type", "extends", "implements", "new", "this", "public", "private", "readonly", "async",
        "await", "null", "undefined", "true", "false", "enum", "namespace",
    ),
    "java": (
        "public", "private", "protected", "class", "interface", "extends", "implements", "return",
        "if", "else", "for", "while", "switch", "case", "break", "new", "this", "static", "final",
        "void", "int", "long", "double", "boolean", "String", "try", "catch", "finally", "throw", "null",
    ),
    "cpp": (
        "int", "long", "double", "float", "char", "bool", "void", "auto", "const", "class", "struct",
        "public", "private", "return", "if", "else", "for", "while", "switch", "case", "break",
        "new", "delete", "this", "template", "typename", "namespace", "using", "nullptr", "true", "false",
    ),
    "go": (
        "func", "package", "import", "return", "if", "else", "for", "range", "switch", "case",
        "break", "type", "struct", "interface", "map", "chan", "go", "defer", "var", "const",
        "nil", "true", "false", "make", "new",
    ),
    "sql": (
        "select", "from", "where", "join", "left", "right", "inner", "outer", "on", "group", "by",
        "order", "having", "insert", "into", "values", "update", "set", "delete", "create", "table",
        "index", "and", "or", "not", "null", "as", "distinct", "limit", "count", "sum", "avg",
    ),
}

LANGUAGES: tuple[str, ...] = ("python", "javascript", "typescript", "java", "cpp", "go", "sql")


def _fmt(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.DemiBold)
    f.setFontItalic(italic)
    return f


class CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document, language: str = "python") -> None:
        super().__init__(document)
        self._kw = _fmt(Color.CODE_KEYWORD, bold=True)
        self._str = _fmt(Color.CODE_STRING)
        self._num = _fmt(Color.CODE_NUMBER)
        self._comment = _fmt(Color.CODE_COMMENT, italic=True)
        self._func = _fmt(Color.CODE_FUNC)
        self.set_language(language)

    def set_language(self, language: str) -> None:
        self._language = language if language in _KEYWORDS else "python"
        words = _KEYWORDS[self._language]
        self._kw_re = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b")
        self._comment_token = "--" if self._language == "sql" else "//"
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        for match in re.finditer(r"\b[A-Za-z_]\w*(?=\s*\()", text):
            self.setFormat(match.start(), match.end() - match.start(), self._func)
        for match in self._kw_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._kw)
        for match in re.finditer(r"\b\d+(\.\d+)?\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self._num)
        for match in re.finditer(r"(\"[^\"]*\"|'[^']*'|`[^`]*`)", text):
            self.setFormat(match.start(), match.end() - match.start(), self._str)
        if self._language == "python":
            hash_pos = text.find("#")
            if hash_pos >= 0:
                self.setFormat(hash_pos, len(text) - hash_pos, self._comment)
        token = self._comment_token
        pos = text.find(token)
        if pos >= 0:
            self.setFormat(pos, len(text) - pos, self._comment)


class _LineNumbers(QWidget):
    def __init__(self, editor: CodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    """带行号与语法高亮的沉浸式代码编辑器。"""

    def __init__(self, language: str = "python") -> None:
        super().__init__()
        font = QFont(MONO_FAMILY.split(",")[0].strip('"'))
        font.setPixelSize(14)
        self.setFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {Color.CODE_BG}; color: {Color.TEXT}; "
            f"border: 1px solid {Color.BORDER_STRONG}; border-radius: 12px; padding: 8px; "
            f"selection-background-color: {Color.PRIMARY}; selection-color: #FFFFFF; }}"
        )
        self._highlighter = CodeHighlighter(self.document(), language)
        self._numbers = _LineNumbers(self)
        self.blockCountChanged.connect(lambda _: self._update_margins())
        self.updateRequest.connect(self._on_update)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_margins()
        self._highlight_current_line()

    def set_language(self, language: str) -> None:
        self._highlighter.set_language(language)

    def line_number_width(self) -> int:
        digits = max(2, len(str(self.blockCount())))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margins(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _on_update(self, rect: QRect, dy: int) -> None:
        if dy:
            self._numbers.scroll(0, dy)
        else:
            self._numbers.update(0, rect.y(), self._numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margins()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._numbers.setGeometry(QRect(cr.left(), cr.top(), self.line_number_width(), cr.height()))

    def _highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(Color.CODE_LINE_HL))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._numbers)
        painter.fillRect(event.rect(), QColor(Color.SURFACE_SUBTLE))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        painter.setPen(QColor(Color.TEXT_FAINT))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0, int(top), self._numbers.width() - 8, self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, str(number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1
        painter.end()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Tab:
            self.insertPlainText("    ")
            return
        super().keyPressEvent(event)

    def set_source(self, text: str) -> None:
        self.setPlainText(text)

    def source(self) -> str:
        return self.toPlainText()

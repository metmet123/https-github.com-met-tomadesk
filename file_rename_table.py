"""Spreadsheet editor with explicit, journaled file execution."""
from pathlib import Path
from difflib import SequenceMatcher
from html import escape
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QColor, QKeySequence, QTextDocument, QAbstractTextDocumentLayout
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidgetItem, QHeaderView, QApplication, QStyledItemDelegate,
    QStyle, QStyleOptionViewItem, QCheckBox, QMessageBox,
)
from file_rename import compose_name, mark_edge_spaces, load_files, parse_clipboard, format_clipboard
from rename_engine import validate
from rename_fill import extend_series
from rename_fill_table import FillTable


class PreviewDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        markup = index.data(Qt.ItemDataRole.UserRole)
        if not markup:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        doc = QTextDocument()
        doc.setDefaultFont(opt.font)
        doc.setDocumentMargin(2)
        doc.setHtml(markup)
        painter.save()
        painter.setClipRect(opt.rect)
        painter.translate(opt.rect.left(), opt.rect.top())
        doc.documentLayout().draw(painter, QAbstractTextDocumentLayout.PaintContext())
        painter.restore()


class FileRenameWindow(QDialog):
    def __init__(self, parent=None, engine=None):
        super().__init__(parent)
        self.engine = engine
        self.errors = {}
        self.results = {}
        self.service_error = ""
        self.setWindowTitle("파일 이름 일괄 변경" if engine else "파일 이름 일괄 변경 · 미리보기")
        self.resize(860, 680)
        self.setMinimumSize(620, 400)
        self.setAcceptDrops(True)
        self.paths = []
        self.input_columns = 3
        self._undo = []
        self._redo = []
        self._restoring = False
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        self.location = QLabel("파일을 이 창으로 끌어다 놓으세요.")
        self.location.setWordWrap(True)
        layout.addWidget(self.location)
        row = QHBoxLayout()
        row.addWidget(QLabel("칸 사이 문자"))
        self.separator = QLineEdit()
        self.separator.setPlaceholderText("없음")
        self.separator.setAccessibleName("칸 사이에 넣을 문자")
        self.separator.setMaximumWidth(100)
        row.addWidget(self.separator)
        self.add_column = QPushButton("열 추가")
        self.remove_column = QPushButton("열 삭제")
        row.addWidget(self.add_column)
        row.addWidget(self.remove_column)
        row.addStretch()
        self.execute_button = QPushButton("이름 바꾸기")
        self.execute_button.setEnabled(False)
        self.execute_button.setToolTip("현재는 미리보기 단계입니다. 실제 변경은 3단계에서 제공됩니다.")
        row.addWidget(self.execute_button)
        for button in (self.add_column, self.remove_column, self.execute_button):
            button.setAutoDefault(False)
        layout.addLayout(row)
        edit_row = QHBoxLayout()
        for attribute, label, callback in (
            ("undo_button", "되돌리기", self.undo),
            ("redo_button", "다시 실행", self.redo),
            ("fill_button", "현재 이름 채우기", self.fill_names),
            ("remove_rows_button", "목록에서 제거", self.remove_rows),
        ):
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(callback)
            setattr(self, attribute, button)
            edit_row.addWidget(button)
        layout.addLayout(edit_row)
        if engine:
            self.setMinimumHeight(470)
            execution_row = QHBoxLayout()
            self.skip_invalid = QCheckBox("문제 행 제외")
            self.problems_only = QCheckBox("문제 행만")
            self.copy_errors_button = QPushButton("사유 복사")
            self.file_undo_button = QPushButton("파일 변경 취소")
            self.recover_button = QPushButton("미완료 복구")
            for widget in (self.skip_invalid, self.problems_only, self.copy_errors_button,
                           self.file_undo_button, self.recover_button):
                execution_row.addWidget(widget)
                if isinstance(widget, QPushButton):
                    widget.setAutoDefault(False)
            layout.addLayout(execution_row)
            self.skip_invalid.toggled.connect(self.refresh_previews)
            self.problems_only.toggled.connect(self._filter_problems)
            self.copy_errors_button.clicked.connect(self.copy_errors)
            self.file_undo_button.clicked.connect(self.undo_files)
            self.recover_button.clicked.connect(self.recover_files)
            self.execute_button.clicked.connect(self.execute_files)
            self.execute_button.setToolTip("검사와 최종 확인 후 실제 파일 이름을 변경합니다.")
            self.file_undo_button.setToolTip("표 Ctrl+Z와 별개입니다. 최근 실행 10건 안에서 마지막 미취소 실행을 취소합니다.")
            self.recover_button.setToolTip(str(engine.path))
        self.table = FillTable(0, 5, self._fill_allowed)
        self.table.fillRequested.connect(self.fill_series)
        # Keep the working area usable even after an application-wide font/theme
        # change; Qt may grow the dialog rather than squeezing rows away.
        self.table.setMinimumHeight(210)
        self.table.setSortingEnabled(False)
        self.table.setAcceptDrops(False)
        self.table.viewport().setAcceptDrops(False)
        self.table.installEventFilter(self)
        self.table.setItemDelegate(PreviewDelegate(self.table))
        self.table.verticalHeader().setSectionsMovable(True)
        self.table.verticalHeader().sectionMoved.connect(self._row_moved)
        self.table.verticalHeader().setToolTip("행 번호를 끌어 순서를 바꿉니다. 파일과 입력값이 함께 이동합니다.")
        layout.addWidget(self.table, 1)
        self.status = QLabel("모든 입력 칸이 비어 있으면 건너뜁니다. 실행 전 확인 창에서 대상 이름을 확인하세요."
                             if engine else "미리보기만 제공합니다. 모든 입력 칸이 비어 있으면 건너뜁니다.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.totals = QLabel()
        layout.addWidget(self.totals)
        hint = QLabel("Ctrl+C/V 복사·붙여넣기 · Ctrl+D 복사 채우기 · Delete 비우기 · Ctrl+Z/Y 되돌리기\n파란 모서리를 아래로 끌어 연속 채우기 · Esc 취소 · 공백은 · 표시 · 행 번호 끌기")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.separator.textChanged.connect(self.refresh_previews)
        self.table.itemChanged.connect(self._item_changed)
        self.add_column.clicked.connect(lambda: self.change_columns(1))
        self.remove_column.clicked.connect(lambda: self.change_columns(-1))
        self._headers()
        self._committed = self._snapshot()
        self._history_buttons()
        self.refresh_previews()

    def _names(self):
        return [compose_name(path, parts, self.separator.text())
                for path, parts in zip(self.paths, self._snapshot()[3])]

    def _filter_problems(self, *_, clear_selection=True):
        if not self.engine:
            return
        if clear_selection:
            self.table.cancel_fill()
            self.table.clearSelection()
        filtered = self.problems_only.isChecked()
        for row, path in enumerate(self.paths):
            problem = row in self.errors or self.results.get(str(path), "").startswith(("실패", "복구 필요", "미실행"))
            self.table.setRowHidden(row, filtered and not problem)
        self.table.verticalHeader().setSectionsMovable(not filtered)

    def _execution_state(self):
        if not self.engine:
            return
        names = self._names()
        self.errors = validate(self.paths, names)
        for row, path in enumerate(self.paths):
            item = self.table.item(row, self.input_columns + 1)
            result = self.results.get(str(path), "")
            if row in self.errors:
                item.setBackground(QColor("#fecaca"))
                item.setData(Qt.ItemDataRole.UserRole, None)
                item.setToolTip(self.errors[row] + ("\n" + result if result else ""))
            elif names[row] and names[row].startswith(" "):
                item.setToolTip(item.toolTip() + "\n주의: 이름 앞 공백을 그대로 유지합니다.")
            if result:
                item.setToolTip(item.toolTip() + "\n" + result)
                self.table.item(row, 0).setToolTip(str(path) + "\n" + result)
        try:
            pending = self.engine.pending()
            candidate = self.engine.undo_candidate() if not pending else []
            self.service_error = ""
        except Exception as exc:
            pending, candidate = [], []
            self.service_error = "실행 기록을 읽을 수 없어 변경을 막았습니다: " + str(exc)
        valid = any(name is not None and name != p.name and row not in self.errors
                    for row, (p, name) in enumerate(zip(self.paths, names)))
        self.execute_button.setEnabled(valid and not pending and not self.service_error
                                       and (not self.errors or self.skip_invalid.isChecked()))
        self.file_undo_button.setEnabled(bool(candidate) and not self.service_error)
        self.recover_button.setEnabled(bool(pending) and not self.service_error)
        if pending:
            self.status.setText("미완료 작업이 있습니다. 미완료 복구를 확인하기 전에는 새 실행을 할 수 없습니다.")
        elif self.service_error:
            self.status.setText(self.service_error)
        self.totals.setText(self.totals.text().replace(" (실제 파일 변경 없음)", f" · 문제 {len(self.errors)}개"))
        self._filter_problems(clear_selection=False)

    def copy_errors(self):
        lines = [f"{self.paths[row]}\t{reason}" for row, reason in sorted(self.errors.items())]
        lines.extend(f"{path}\t{result}" for path, result in self.results.items() if not result.startswith("성공"))
        QApplication.clipboard().setText("\n".join(lines))

    def _confirm_files(self, title, rows, note=""):
        box = QMessageBox(QMessageBox.Icon.Warning, title,
                          f"{len(rows)}개 파일의 이름을 실제로 변경합니다.\n{note}\n기존 파일을 덮어쓰지 않습니다.",
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setDetailedText("\n".join(f"{r['src']} → {r['dst']}" for r in rows))
        return box.exec() == QMessageBox.StandardButton.Yes

    def _consume_batch(self, batch):
        state = self._snapshot()
        paths, values = list(state[0]), list(state[3])
        by_source = {r["src"]: (r, g) for g in batch["groups"] for r in g["rows"]}
        self.results = {}
        counts = {"done": 0, "rolled_back": 0, "recovery_required": 0, "pending": 0}
        for group in batch["groups"]:
            counts[group["state"]] = counts.get(group["state"], 0) + len(group["rows"])
            for row in group["rows"]:
                target = row["dst"] if group["state"] == "done" else row["src"]
                label = {"done": "성공", "rolled_back": "실패·원상복구", "recovery_required": "복구 필요", "pending": "미실행"}.get(group["state"], "복구 필요")
                self.results[target] = label + (": " + group["error"] if group["error"] else "")
        for i, path in enumerate(paths):
            if str(path) in by_source:
                row, group = by_source[str(path)]
                if group["state"] == "done":
                    paths[i] = Path(row["dst"])
                    values[i] = ("",) * state[1]
        self._undo.clear()
        self._redo.clear()
        self._restore((tuple(paths), state[1], state[2], tuple(values)))
        self.status.setText(f"성공 {counts['done']}개 · 실패/복구됨 {counts['rolled_back']}개 · 복구 필요 {counts['recovery_required']}개 · 미실행 {counts['pending']}개")

    def execute_files(self):
        if not self.engine:
            return
        try:
            rows = self.engine.prepare(self.paths, self._names(), self.skip_invalid.isChecked())
            if not rows:
                self.status.setText("변경할 유효한 파일이 없습니다.")
                return
            warning = "문제 행은 제외합니다. " if self.skip_invalid.isChecked() else ""
            if any(Path(r["dst"]).name.startswith(" ") for r in rows):
                warning += "앞 공백이 있는 이름을 포함합니다."
            if not self._confirm_files("파일 이름 변경 확인", rows, warning):
                return
            self.setEnabled(False)
            self._consume_batch(self.engine.execute(rows))
        except Exception as exc:
            self.refresh_previews()
            self.status.setText("변경 중단: " + str(exc))
        finally:
            self.setEnabled(True)

    def undo_files(self):
        try:
            rows = self.engine.undo_candidate()
            if not rows or not self._confirm_files("파일 변경 취소 확인", rows, "표 편집 Undo와 별개의 실제 파일 작업입니다."):
                return
            self.setEnabled(False)
            self._consume_batch(self.engine.undo({r["original_group"] for r in rows}))
        except Exception as exc:
            self.refresh_previews()
            self.status.setText("파일 변경 취소 중단: " + str(exc))
        finally:
            self.setEnabled(True)

    def recover_files(self):
        try:
            batches = self.engine.pending()
            rows = [r for b in batches for g in b["groups"] if g["state"] not in {"done", "rolled_back"} for r in g["rows"]]
            box = QMessageBox(QMessageBox.Icon.Warning, "미완료 복구 확인",
                              "완료된 묶음은 유지하고 중단된 묶음을 실행 전 이름으로 복구합니다.\n확인 후 표 목록/입력은 비웁니다. 원본 파일은 삭제하지 않습니다.",
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            box.setDetailedText("\n\n".join(f"원본: {r['src']}\n임시: {r['tmp']}\n목표: {r['dst']}" for r in rows))
            if not batches or box.exec() != QMessageBox.StandardButton.Yes:
                return
            self.setEnabled(False)
            recovered = self.engine.recover()
            self.results = {r["src"]: "복구 필요: " + g["error"] for b in recovered for g in b["groups"]
                            if g["state"] == "recovery_required" for r in g["rows"]}
            self._undo.clear()
            self._redo.clear()
            self._restore(((), self.input_columns, self.separator.text(), ()))
            self.status.setText("복구 필요 항목이 남았습니다. 사유 복사와 기록 경로를 확인하세요." if self.engine.pending()
                                else "중단된 작업 복구를 마쳤습니다. 파일 목록을 다시 불러오세요.")
        except Exception as exc:
            self.refresh_previews()
            self.status.setText("복구 중단: " + str(exc))
        finally:
            self.setEnabled(True)

    def showEvent(self, event):
        super().showEvent(event)
        if self.engine:
            self.refresh_previews()

    def _snapshot(self):
        return (tuple(self.paths), self.input_columns, self.separator.text(),
                tuple(tuple(self.table.item(r, c).text() for c in range(1, self.input_columns + 1))
                      for r in range(self.table.rowCount())))

    def _remember(self):
        if self._restoring:
            return
        state = self._snapshot()
        if state != self._committed:
            self._undo.append(self._committed)
            self._undo = self._undo[-100:]
            self._redo.clear()
            self._committed = state
        self._history_buttons()

    def _history_buttons(self):
        self.undo_button.setEnabled(bool(self._undo))
        self.redo_button.setEnabled(bool(self._redo))

    def _restore(self, state):
        paths, columns, separator, values = state
        self._restoring = True
        self.table.blockSignals(True)
        self.separator.blockSignals(True)
        try:
            self.paths = list(paths)
            self.input_columns = columns
            self.separator.setText(separator)
            self.table.setRowCount(0)
            self.table.setColumnCount(columns + 2)
            self.table.setRowCount(len(paths))
            for r, path in enumerate(paths):
                original = self._readonly(path.name)
                original.setToolTip(str(path))
                self.table.setItem(r, 0, original)
                for c, value in enumerate(values[r], 1):
                    self.table.setItem(r, c, QTableWidgetItem(value))
                self.table.setItem(r, columns + 1, self._readonly(""))
            self._headers()
        finally:
            self.table.blockSignals(False)
            self.separator.blockSignals(False)
        self.refresh_previews()
        self._restoring = False
        self._committed = state
        self._history_buttons()

    def undo(self):
        if self._undo:
            self._redo.append(self._snapshot())
            self._restore(self._undo.pop())

    def redo(self):
        if self._redo:
            self._undo.append(self._snapshot())
            self._restore(self._redo.pop())

    def _range(self, editable=True):
        ranges = self.table.selectedRanges()
        if len(ranges) != 1:
            self.status.setText("연속된 직사각형 범위 하나를 선택하세요.")
            return None
        area = ranges[0]
        if any(self.table.isRowHidden(r) for r in range(area.topRow(), area.bottomRow() + 1)):
            self.status.setText("숨겨진 행이 포함된 범위입니다. 문제 행 필터를 해제하세요.")
            return None
        if editable and not (1 <= area.leftColumn() <= area.rightColumn() <= self.input_columns):
            self.status.setText("편집은 입력 열에서만 가능합니다.")
            return None
        return area

    def _apply_cells(self, changes):
        self.table.blockSignals(True)
        try:
            for row, col, value in changes:
                self.table.item(row, col).setText(value)
        finally:
            self.table.blockSignals(False)
        self.refresh_previews()

    def copy_cells(self):
        area = self._range(False)
        if area is None:
            return
        inputs = self._snapshot()[3]
        rows = []
        for r in range(area.topRow(), area.bottomRow() + 1):
            values = []
            for c in range(area.leftColumn(), area.rightColumn() + 1):
                if c == self.input_columns + 1:
                    values.append(compose_name(self.paths[r], inputs[r], self.separator.text()) or self.paths[r].name)
                else:
                    values.append(self.table.item(r, c).text())
            rows.append(values)
        QApplication.clipboard().setText(format_clipboard(rows))

    def paste_cells(self):
        area = self._range()
        if area is None:
            return
        try:
            rows = parse_clipboard(QApplication.clipboard().text())
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        r, c = area.topRow(), area.leftColumn()
        if r + len(rows) > len(self.paths) or c + len(rows[0]) - 1 > self.input_columns:
            self.status.setText("붙여넣기 범위가 표를 넘습니다. 아무 칸도 변경하지 않았습니다.")
            return
        if any(self.table.isRowHidden(i) for i in range(r, r + len(rows))):
            self.status.setText("숨겨진 행에는 붙여넣을 수 없습니다. 필터를 해제하세요.")
            return
        self._apply_cells([(r + i, c + j, value) for i, row in enumerate(rows) for j, value in enumerate(row)])
        self.status.setText("붙여넣기 완료 · Ctrl+Z로 한 번에 되돌릴 수 있습니다.")

    def clear_cells(self):
        area = self._range()
        if area is not None:
            self._apply_cells([(r, c, "") for r in range(area.topRow(), area.bottomRow() + 1)
                               for c in range(area.leftColumn(), area.rightColumn() + 1)])

    def fill_down(self):
        area = self._range()
        if area is not None:
            self._apply_cells([(r, c, self.table.item(area.topRow(), c).text())
                               for r in range(area.topRow() + 1, area.bottomRow() + 1)
                               for c in range(area.leftColumn(), area.rightColumn() + 1)])

    def _fill_allowed(self):
        return not self.engine or not self.problems_only.isChecked()

    def fill_series(self, top, bottom, left, right, target):
        if (not self._fill_allowed() or not 0 <= top <= bottom < target < self.table.rowCount()
                or not 1 <= left <= right <= self.input_columns
                or any(self.table.isRowHidden(r) for r in range(top, target + 1))):
            self.status.setText("입력 열의 보이는 범위만 아래로 채울 수 있습니다.")
            return
        changes = []
        for column in range(left, right + 1):
            seeds = [self.table.item(row, column).text() for row in range(top, bottom + 1)]
            generated = extend_series(seeds, target - bottom)
            changes.extend((row, column, value) for row, value in zip(range(bottom + 1, target + 1), generated))
        self._apply_cells(changes)
        self.status.setText(f"{len(changes)}개 칸 채우기 완료 · Ctrl+Z로 한 번에 되돌릴 수 있습니다. 파일은 변경하지 않았습니다.")

    def fill_names(self):
        area = self._range()
        if area is None:
            return
        if area.columnCount() != 1:
            self.status.setText("현재 이름을 채울 입력 열 하나만 선택하세요.")
            return
        self._apply_cells([(r, area.leftColumn(), self.paths[r].stem)
                           for r in range(area.topRow(), area.bottomRow() + 1)])
        self.status.setText("마지막 확장자를 뺀 현재 이름을 채웠습니다. Ctrl+Z로 되돌릴 수 있습니다.")

    def remove_rows(self):
        selected = {index.row() for index in self.table.selectedIndexes()
                    if not self.table.isRowHidden(index.row())}
        if not selected:
            self.status.setText("목록에서 제거할 행을 선택하세요.")
            return
        keep = [i for i in range(len(self.paths)) if i not in selected]
        self._replace_rows(keep)
        self.status.setText(f"{len(selected)}개 행을 목록에서만 제거했습니다. 파일은 삭제하지 않았습니다.")

    def _replace_rows(self, order):
        before = self._snapshot()
        self._restore((tuple(before[0][i] for i in order), before[1], before[2],
                       tuple(before[3][i] for i in order)))
        self._committed = before
        self._remember()

    def _row_moved(self, logical, old_visual, new_visual):
        header = self.table.verticalHeader()
        order = [header.logicalIndex(i) for i in range(header.count())]
        header.blockSignals(True)
        try:
            for logical_index in range(header.count()):
                header.moveSection(header.visualIndex(logical_index), logical_index)
        finally:
            header.blockSignals(False)
        self._replace_rows(order)

    def eventFilter(self, watched, event):
        if watched is self.table and event.type() == QEvent.Type.KeyPress:
            if self.table._fill_area:
                if event.key() == Qt.Key.Key_Escape:
                    self.table.cancel_fill()
                return True
            for key, callback in ((QKeySequence.StandardKey.Copy, self.copy_cells),
                                  (QKeySequence.StandardKey.Paste, self.paste_cells),
                                  (QKeySequence.StandardKey.Undo, self.undo),
                                  (QKeySequence.StandardKey.Redo, self.redo)):
                if event.matches(key):
                    callback()
                    return True
            if event.key() == Qt.Key.Key_Delete:
                self.clear_cells()
                return True
            if event.key() == Qt.Key.Key_D and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self.fill_down()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                row = min(self.table.currentRow() + 1, self.table.rowCount() - 1)
                if row >= 0:
                    self.table.setCurrentCell(row, max(1, min(self.table.currentColumn(), self.input_columns)))
                return True
        return super().eventFilter(watched, event)

    def _headers(self):
        self.table.setHorizontalHeaderLabels(
            ["현재 이름"] + [str(i + 1) for i in range(self.input_columns)] + ["바뀔 이름"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.add_column.setEnabled(self.input_columns < 5)
        self.remove_column.setEnabled(self.input_columns > 2)

    @staticmethod
    def _readonly(text):
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def add_paths(self, paths):
        accepted, skipped = load_files(paths, self.paths)
        self.table.blockSignals(True)
        try:
            for path in accepted:
                row = self.table.rowCount()
                self.paths.append(path)
                self.table.insertRow(row)
                original = self._readonly(path.name)
                original.setToolTip(str(path))
                self.table.setItem(row, 0, original)
                for col in range(1, self.input_columns + 1):
                    self.table.setItem(row, col, QTableWidgetItem(""))
                self.table.setItem(row, self.input_columns + 1, self._readonly(""))
        finally:
            self.table.blockSignals(False)
        self.status.setText(f"{len(accepted)}개 추가 · 폴더/없는 파일 {len(skipped)}개 제외"
                            + (" · 실행 전 확인 필요" if self.engine else " · 미리보기만 제공"))
        self.status.setToolTip("\n".join(skipped))
        self.refresh_previews()

    def change_columns(self, delta):
        count = self.input_columns + delta
        if not 2 <= count <= 5:
            return
        if delta < 0 and any(self.table.item(r, self.input_columns).text() for r in range(self.table.rowCount())):
            self.status.setText("마지막 입력 열을 비운 뒤 삭제하세요.")
            return
        self.table.blockSignals(True)
        if delta > 0:
            self.table.insertColumn(self.input_columns + 1)
            for row in range(self.table.rowCount()):
                self.table.setItem(row, self.input_columns + 1, QTableWidgetItem(""))
        else:
            self.table.removeColumn(self.input_columns)
        self.input_columns = count
        self._headers()
        self.table.blockSignals(False)
        self.refresh_previews()

    def _item_changed(self, item):
        if 1 <= item.column() <= self.input_columns:
            self.refresh_previews()

    def refresh_previews(self, *_):
        changed = skipped = unchanged = 0
        self.table.blockSignals(True)
        try:
            for row, path in enumerate(self.paths):
                parts = [self.table.item(row, col).text() for col in range(1, self.input_columns + 1)]
                name = compose_name(path, parts, self.separator.text())
                item = self.table.item(row, self.input_columns + 1)
                item.setText(mark_edge_spaces(name) if name is not None else "건너뜀")
                item.setToolTip(name if name is not None else path.name + " (변경 없음)")
                item.setForeground(QColor("#64748b"))
                different = name is not None and name != path.name
                changed += int(different)
                skipped += int(name is None)
                unchanged += int(name == path.name)
                markup = None
                if different:
                    pieces = []
                    shown = mark_edge_spaces(name)
                    for tag, a, b, c, d in SequenceMatcher(None, path.name, name).get_opcodes():
                        value = escape(shown[c:d]).replace(" ", "&nbsp;").replace("\n", "↵").replace("\t", "⇥")
                        pieces.append(value if tag == "equal" else '<span style="background-color:#fef08a;color:#1e293b">' + value + '</span>')
                    markup = '<span style="color:#64748b">' + ''.join(pieces) + '</span>'
                item.setData(Qt.ItemDataRole.UserRole, markup)
                item.setBackground(QColor("#f0f9ff") if different else QColor("transparent"))
        finally:
            self.table.blockSignals(False)
        folders = list(dict.fromkeys(str(path.parent) for path in self.paths))
        self.location.setText(
            f"{folders[0] if len(folders) == 1 else str(len(folders)) + '개 폴더'} · {len(self.paths)}개 파일"
            if folders else "파일을 이 창으로 끌어다 놓으세요."
        )
        self.location.setToolTip("\n".join(folders))
        self.totals.setText(f"변경 {changed}개 · 동일 {unchanged}개 · 건너뜀 {skipped}개 (실제 파일 변경 없음)")
        self.table.blockSignals(True)
        try:
            self._execution_state()
        finally:
            self.table.blockSignals(False)
        self._remember()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_paths([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

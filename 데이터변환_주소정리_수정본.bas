Option Explicit

Private Const DATA_START_ROW As Long = 4
Private Const PUBLIC_START_ROW As Long = 4
Private Const NOTICE_START_ROW As Long = 3

Public Sub 데이터를_공문_통지서로_변환()

    Dim wsData As Worksheet
    Dim wsPublic As Worksheet
    Dim wsNotice As Worksheet
    Dim lastDataRow As Long
    Dim lastPublicRow As Long
    Dim lastNoticeRow As Long
    Dim sourceRow As Long
    Dim publicRow As Long
    Dim noticeRow As Long
    Dim personCount As Long
    Dim errorMessage As String
    Dim formattedAddress As String

    Set wsData = ThisWorkbook.Worksheets("데이터")
    Set wsPublic = ThisWorkbook.Worksheets("공문")
    Set wsNotice = ThisWorkbook.Worksheets("통지서")

    lastDataRow = wsData.Cells(wsData.Rows.Count, "B").End(xlUp).Row

    If lastDataRow < DATA_START_ROW Then
        MsgBox "데이터 시트에 입력된 대상자가 없습니다.", vbExclamation
        Exit Sub
    End If

    '변환 전 필수값 확인
    For sourceRow = DATA_START_ROW To lastDataRow
        If Trim$(CellText(wsData.Cells(sourceRow, "B"))) <> "" Then
            errorMessage = ValidateDataRow(wsData, sourceRow)

            If errorMessage <> "" Then
                MsgBox sourceRow & "행: " & errorMessage, vbExclamation
                Exit Sub
            End If
        End If
    Next sourceRow

    Application.ScreenUpdating = False
    Application.EnableEvents = False

    On Error GoTo ErrorHandler

    '기존 공문 결과 삭제: 서식은 유지
    lastPublicRow = wsPublic.Cells(wsPublic.Rows.Count, "B").End(xlUp).Row
    If lastPublicRow >= PUBLIC_START_ROW Then
        wsPublic.Range("B" & PUBLIC_START_ROW & ":D" & lastPublicRow).ClearContents
    End If

    '기존 통지서 결과 삭제: 서식은 유지
    lastNoticeRow = wsNotice.Cells(wsNotice.Rows.Count, "B").End(xlUp).Row
    If lastNoticeRow >= NOTICE_START_ROW Then
        wsNotice.Range("B" & NOTICE_START_ROW & ":G" & lastNoticeRow).ClearContents
    End If

    personCount = 0

    For sourceRow = DATA_START_ROW To lastDataRow

        If Trim$(CellText(wsData.Cells(sourceRow, "B"))) <> "" Then

            personCount = personCount + 1
            publicRow = PUBLIC_START_ROW + personCount - 1
            noticeRow = NOTICE_START_ROW + (personCount - 1) * 2
            formattedAddress = FormatAddress(CellText(wsData.Cells(sourceRow, "F")))

            '공문 시트: 1명당 1행
            If publicRow > PUBLIC_START_ROW Then
                wsPublic.Range("B" & PUBLIC_START_ROW & ":D" & PUBLIC_START_ROW).Copy _
                    Destination:=wsPublic.Range("B" & publicRow & ":D" & publicRow)
                wsPublic.Range("B" & publicRow & ":D" & publicRow).ClearContents
            End If

            wsPublic.Cells(publicRow, "B").Value = CellText(wsData.Cells(sourceRow, "B")) '성명
            With wsPublic.Cells(publicRow, "C")
                .NumberFormat = "@"
                .Value = ResidentNumberFront(wsData.Cells(sourceRow, "C")) '생년월일
            End With
            wsPublic.Cells(publicRow, "D").Value = formattedAddress '주소

            '통지서 시트: 1명당 2행
            If noticeRow > NOTICE_START_ROW Then
                wsNotice.Range("B" & NOTICE_START_ROW & ":G" & NOTICE_START_ROW + 1).Copy _
                    Destination:=wsNotice.Range("B" & noticeRow & ":G" & noticeRow + 1)
                wsNotice.Range("B" & noticeRow & ":G" & noticeRow + 1).ClearContents
            End If

            '통지서 첫 번째 행
            wsNotice.Cells(noticeRow, "B").Value = "성　명"
            wsNotice.Cells(noticeRow, "C").Value = CellText(wsData.Cells(sourceRow, "B"))
            wsNotice.Cells(noticeRow, "D").Value = "주민등록번호"
            wsNotice.Cells(noticeRow, "E").Value = MaskResidentNumber(wsData.Cells(sourceRow, "C"))
            wsNotice.Cells(noticeRow, "F").Value = "전화번호"
            wsNotice.Cells(noticeRow, "G").Value = CellText(wsData.Cells(sourceRow, "D"))

            '통지서 두 번째 행
            wsNotice.Cells(noticeRow + 1, "B").Value = "주　소"
            wsNotice.Cells(noticeRow + 1, "C").Value = _
                formattedAddress & _
                " (" & PostalCodeText(wsData.Cells(sourceRow, "E")) & ")"
        End If

    Next sourceRow

    Application.CutCopyMode = False
    Application.ScreenUpdating = True
    Application.EnableEvents = True

    MsgBox personCount & "명을 공문 및 통지서 양식으로 변환했습니다.", vbInformation
    Exit Sub

ErrorHandler:
    Application.CutCopyMode = False
    Application.ScreenUpdating = True
    Application.EnableEvents = True
    MsgBox "변환 중 오류가 발생했습니다: " & Err.Description, vbCritical

End Sub

Private Function ValidateDataRow(ByVal ws As Worksheet, ByVal rowNumber As Long) As String

    If CellText(ws.Cells(rowNumber, "B")) = "" Then
        ValidateDataRow = "이름이 비어 있습니다."
    ElseIf Len(ResidentDigits(ws.Cells(rowNumber, "C"))) < 6 Then
        ValidateDataRow = "주민등록번호 앞 6자리를 확인하세요."
    ElseIf CellText(ws.Cells(rowNumber, "D")) = "" Then
        ValidateDataRow = "전화번호가 비어 있습니다."
    ElseIf CellText(ws.Cells(rowNumber, "E")) = "" Then
        ValidateDataRow = "우편번호가 비어 있습니다."
    ElseIf CellText(ws.Cells(rowNumber, "F")) = "" Then
        ValidateDataRow = "주소가 비어 있습니다."
    End If

End Function

Private Function ResidentNumberFront(ByVal targetCell As Range) As String
    ResidentNumberFront = Left$(ResidentDigits(targetCell), 6)
End Function

Private Function ResidentDigits(ByVal targetCell As Range) As String

    Dim digits As String

    digits = CleanDigits(CellText(targetCell))

    '생년월일 또는 전체 주민등록번호가 숫자로 저장되어
    '맨 앞의 0이 사라진 경우 이를 복원한다.
    If Len(digits) = 5 Or Len(digits) = 12 Then
        digits = "0" & digits
    End If

    ResidentDigits = digits

End Function

Private Function MaskResidentNumber(ByVal targetCell As Range) As String
    MaskResidentNumber = ResidentNumberFront(targetCell) & "-*****"
End Function

Private Function PostalCodeText(ByVal targetCell As Range) As String
    Dim postalCode As String

    postalCode = CleanDigits(CellText(targetCell))
    PostalCodeText = Right$("00000" & postalCode, 5)
End Function

Private Function FormatAddress(ByVal sourceText As String) As String

    Dim result As String
    Dim openingParenthesisPosition As Long

    result = Trim$(sourceText)

    If Left$(result, Len("부산광역시")) = "부산광역시" Then
        result = Trim$(Mid$(result, Len("부산광역시") + 1))
    End If

    openingParenthesisPosition = InStr(1, result, "(", vbBinaryCompare)

    If openingParenthesisPosition > 0 Then
        result = Trim$(Left$(result, openingParenthesisPosition - 1))
    End If

    FormatAddress = result

End Function

Private Function CellText(ByVal targetCell As Range) As String
    If IsError(targetCell.Value) Then Exit Function
    CellText = Trim$(CStr(targetCell.Value2))
End Function

Private Function CleanDigits(ByVal sourceText As String) As String

    Dim index As Long
    Dim oneCharacter As String

    For index = 1 To Len(sourceText)
        oneCharacter = Mid$(sourceText, index, 1)

        If oneCharacter Like "#" Then
            CleanDigits = CleanDigits & oneCharacter
        End If
    Next index

End Function

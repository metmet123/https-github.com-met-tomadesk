package com.toma.companion
import org.junit.Test
import org.junit.Assert.*

class MarkdownTest {
    @Test fun headingChecklistAndNestedDetails() {
        val b=Markdown.parse("# 제목\n- [ ] 할 일\n<details>\n<summary>접기</summary>\n본문\n</details>\n끝")
        assertEquals(1,b[0].level); assertEquals("☐ 할 일",b[1].text)
        assertEquals("▾ 접기",b[2].text); assertEquals(0,b[2].indent)
        assertEquals(1,b[3].indent); assertEquals(0,b[4].indent)
    }
    @Test fun codeDoesNotBecomeHeading() {
        val b=Markdown.parse("```python\n# comment\n```\n## 제목")
        assertEquals(0,b[1].level); assertEquals("# comment",b[1].text); assertEquals(2,b[3].level)
    }
    @Test fun preservesUnicodeAndCheckedItem() {
        val b=Markdown.parse("- [X] 토마 🐦\n  - nested")
        assertEquals("☑ 토마 🐦",b[0].text); assertEquals(1,b[1].indent)
    }
}

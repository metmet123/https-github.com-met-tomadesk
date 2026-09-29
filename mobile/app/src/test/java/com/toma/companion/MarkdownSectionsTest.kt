package com.toma.companion
import org.junit.Test
import org.junit.Assert.*
class MarkdownSectionsTest {
 @Test fun headingsInsideFencesStayCode() {
  val s=MarkdownSections.split("# 제목\n본문\n````kotlin\n# comment\n```\n## still code\n````\n## 다음\n끝")
  assertEquals(2,s.size);assertEquals(1,s[0].level);assertTrue(s[0].body.contains("## still code"));assertEquals(2,s[1].level)
 }
 @Test fun nestedHeadingsAndUnicode() {
  val s=MarkdownSections.split("시작\n# 토마 🐦\n## 하위\n끝\n# 다음")
  assertEquals(listOf(0,1,2,1),s.map { it.level });assertTrue(s[1].heading.contains("🐦"))
 }
 @Test fun indentedCodeIsNotASection() {
  assertEquals(0,MarkdownSections.split("    # 코드\n본문").single().level)
 }
}

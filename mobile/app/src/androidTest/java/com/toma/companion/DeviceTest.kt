package com.toma.companion
import android.content.Intent
import android.view.WindowManager
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.*
import androidx.test.espresso.matcher.ViewMatchers.*
import androidx.test.espresso.assertion.ViewAssertions.*
import org.hamcrest.Matchers.containsString
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DeviceTest {
 @Test fun markdownDocumentRoundtripAndLegacyGuard() {
  val ins=InstrumentationRegistry.getInstrumentation();val args=InstrumentationRegistry.getArguments()
  val legacy=args.getString("legacy")=="true"
  val address="https://127.0.0.1:"+if(legacy)"47833" else "47832"
  val activity=ins.startActivitySync(Intent(ins.targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  ins.runOnMainSync { activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE) }
  fun capture(name:String) {
   Thread.sleep(2500)
   ins.uiAutomation.takeScreenshot()?.let { bmp -> java.io.File(ins.targetContext.getExternalFilesDir(null),name).outputStream().use { bmp.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) } }
  }
  onView(withHint("https://100.x.x.x:47831")).perform(replaceText(address))
  onView(withHint("PC 인증서 SHA-256 지문")).perform(replaceText(args.getString("pin")!!))
  onView(withHint("아이디")).perform(replaceText("qa"))
  onView(withHint("비밀번호")).perform(replaceText(args.getString("password")!!),closeSoftKeyboard())
  onView(withText("로그인 · PC 연결")).perform(scrollTo(),click());Thread.sleep(4000)
  onView(withText("연동 시험")).perform(click())
  val source="# 나의 메모\n\n**굵게** 쓰고 자유롭게 이어가요.\n\n- [ ] 모바일에서 기록하기\n- [x] PC와 연결하기\n\n```kotlin\n# 코드 안의 제목\nprintln(\"토마\")\n```\n\n| 항목 | 상태 |\n| --- | --- |\n| 메모 | 완료 |\n"
  onView(withContentDescription("Markdown 문서")).perform(replaceText(source),closeSoftKeyboard());Thread.sleep(600)
  if(!legacy) {
   capture("md-editor.png")
   onView(withText("미리보기")).perform(click());capture("md-preview.png")
   onView(withContentDescription("접기")).perform(click())
   onView(withText(containsString("굵게"))).check(doesNotExist())
   onView(withContentDescription("펼치기")).perform(click())
  }
  onView(withContentDescription("동기화")).perform(click());Thread.sleep(4000)
  if(legacy) {
   onView(withText(containsString("0.1.2 이상"))).check(matches(isDisplayed()))
   onView(withText("확인")).perform(click())
   onView(withContentDescription("Markdown 문서")).check(matches(isEnabled()))
   assertFalse(Vault(ins.targetContext).read().optBoolean("uncertain"))
  } else {
   onView(withText("연동 시험")).perform(click())
   onView(withContentDescription("Markdown 문서")).check(matches(withText(source)))
   val notes=Vault(ins.targetContext).read().getJSONArray("notes")
   assertTrue((0 until notes.length()).any { notes.getJSONObject(it).optString("title").endsWith("Markdown 변환 전 원본") })
  }
  val vault=Vault(ins.targetContext).read();assertTrue(vault.toString().contains("모바일에서"))
  val encrypted=java.io.File(ins.targetContext.filesDir,"vault.enc").readBytes().toString(Charsets.UTF_8)
  assertFalse(encrypted.contains("모바일에서"));assertFalse(encrypted.contains(vault.getString("token")))
  ins.runOnMainSync { activity.finish() }
 }
}

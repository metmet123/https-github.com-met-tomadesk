package com.toma.companion

import android.app.*
import android.content.*
import android.graphics.Color
import android.graphics.BitmapFactory
import android.os.*
import android.text.*
import android.view.*
import android.widget.*
import org.json.*
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.google.mlkit.vision.common.InputImage
import java.util.UUID
import java.util.concurrent.Executors

class MainActivity: Activity() {
    private lateinit var vault: Vault
    private var state=JSONObject()
    private var unlocked=false
    private var work=false
    private var selected: JSONObject?=null
    private var pickerActive=false
    private var qrResultHandler: ((String)->Unit)?=null
    private val executor=Executors.newSingleThreadExecutor()
    private lateinit var root: LinearLayout
    private var documentInput:EditText?=null
    private val draftHandler=Handler(Looper.getMainLooper())
    private var draftPending=false
    private val writeDraft=Runnable { draftPending=false; save() }
    private fun flushDraft() { draftHandler.removeCallbacks(writeDraft); if(draftPending) { draftPending=false; save() } }
    private val markwon by lazy { io.noties.markwon.Markwon.builder(this)
        .usePlugin(io.noties.markwon.ext.tables.TablePlugin.create(this))
        .usePlugin(io.noties.markwon.ext.tasklist.TaskListPlugin.create(this))
        .usePlugin(io.noties.markwon.ext.strikethrough.StrikethroughPlugin.create()).build() }
    private val ink=TomaStyle.ink
    private val green=TomaStyle.green
    private val folded=mutableSetOf<String>()
    private fun dp(v:Int)=(v*resources.displayMetrics.density).toInt()
    private fun arr(name:String): JSONArray { if(!state.has(name)) state.put(name,JSONArray()); return state.getJSONArray(name) }
    private fun save() { try { vault.write(state) } catch(e:Exception) { toast("저장 실패: ${e.message}") } }
    override fun onCreate(savedInstanceState:Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        window.decorView.systemUiVisibility=View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        vault=Vault(this)
        try { state=vault.read() } catch(e:Exception) { message("보관된 자료를 읽지 못했습니다."); return }
        if(state.optBoolean("paired")) { unlocked=true; home() } else loginScreen()
        handlePairIntent(intent)
    }
    override fun onStop() { flushDraft(); super.onStop() }
    override fun onStart() {
        super.onStart()
        if(::vault.isInitialized && !pickerActive && !unlocked) loginScreen()
    }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); handlePairIntent(intent) }
    private fun handlePairIntent(pairIntent: Intent?) {
        val raw=pairIntent?.dataString ?: return
        pairIntent.data=null
        unlocked=false; loginScreen(); qrResultHandler?.invoke(raw)
    }
    private fun base(title:String, subtitle:String): LinearLayout {
        flushDraft(); documentInput=null
        root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(dp(24),dp(12),dp(24),dp(8)); setBackgroundColor(TomaStyle.paper) }
        root.setOnApplyWindowInsetsListener { v,i -> v.setPadding(dp(24),i.systemWindowInsetTop+dp(12),dp(24),i.systemWindowInsetBottom+dp(8)); i }
        val head=LinearLayout(this).apply { gravity=Gravity.CENTER_VERTICAL; setPadding(0,dp(8),0,dp(8)) }
        head.addView(TextView(this).apply { text=title; textSize=28f; setTextColor(ink); typeface=android.graphics.Typeface.create("sans-serif-medium",android.graphics.Typeface.NORMAL) },LinearLayout.LayoutParams(0,-2,1f))
        head.addView(mascot(40),LinearLayout.LayoutParams(dp(40),dp(40)))
        root.addView(head)
        if(subtitle.isNotEmpty())root.addView(label(subtitle,12f).apply { setTextColor(TomaStyle.muted); setPadding(0,0,0,dp(20)) })
        setContentView(root); root.requestApplyInsets(); return root
    }
    private fun mascot(size:Int)=ImageView(this).apply { setImageResource(R.drawable.toma); contentDescription="토마"; setPadding(dp(size/8),dp(size/8),dp(size/8),dp(size/8)); background=TomaStyle.surface(this@MainActivity,TomaStyle.sage,size/2) }
    private fun label(text:String,size:Float=16f)=TextView(this).apply { this.text=text; textSize=size; setTextColor(ink); setPadding(0,dp(6),0,dp(6)); setLineSpacing(dp(3).toFloat(),1.12f) }
    private fun button(text:String,action:()->Unit)=Button(this).apply {
        this.text=text; isAllCaps=false; textSize=14f; setTextColor(green); typeface=android.graphics.Typeface.create("sans-serif-medium",android.graphics.Typeface.NORMAL)
        background=TomaStyle.touch(this@MainActivity,TomaStyle.sage,14); elevation=0f; stateListAnimator=null; minHeight=dp(48); minimumHeight=dp(48); setPadding(dp(16),dp(8),dp(16),dp(8))
        setOnClickListener { if(!work) action() else toast("동기화 중입니다.") }
    }
    private fun primary(b:Button)=b.apply { background=TomaStyle.touch(this@MainActivity,green,16); setTextColor(Color.WHITE) }
    private fun iconButton(name:String,description:String,action:()->Unit)=ImageButton(this).apply {
        setImageDrawable(TomaStyle.icon(name)); contentDescription=description; background=TomaStyle.touch(this@MainActivity,TomaStyle.paper,16); setPadding(dp(13),dp(13),dp(13),dp(13))
        setOnClickListener { if(!work)action() else toast("동기화 중입니다.") }
    }
    private fun field(hint:String,value:String="")=EditText(this).apply {
        this.hint=hint; contentDescription=hint; setText(value); textSize=15f; setTextColor(ink); setHintTextColor(TomaStyle.muted); setSingleLine(true)
        background=TomaStyle.surface(this@MainActivity,Color.WHITE,14,true); setPadding(dp(16),dp(14),dp(16),dp(14)); minHeight=dp(52)
        layoutParams=LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(12) }
    }
    private fun bottomNav(active:String) {
        val nav=LinearLayout(this).apply { setPadding(0,dp(12),0,0); gravity=Gravity.CENTER }
        listOf(Triple("메모","note",{home()}),Triple("일정","calendar",{agenda()}),Triple("설정","settings",{settings()})).forEach { (title,icon,action) ->
            val tab=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; gravity=Gravity.CENTER; setPadding(0,dp(8),0,dp(6)); background=TomaStyle.touch(this@MainActivity,if(title==active)TomaStyle.sage else TomaStyle.paper,16); contentDescription=title; isFocusable=true; setOnClickListener { if(!work)action() } }
            tab.addView(ImageView(this).apply { setImageDrawable(TomaStyle.icon(icon,if(title==active)green else TomaStyle.muted)); importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_NO },LinearLayout.LayoutParams(dp(22),dp(22)))
            tab.addView(label(title,11f).apply { gravity=Gravity.CENTER; setTextColor(if(title==active)green else TomaStyle.muted); setPadding(0,dp(4),0,0) })
            nav.addView(tab,LinearLayout.LayoutParams(0,-2,1f).apply { marginStart=dp(3); marginEnd=dp(3) })
        }
        root.addView(nav)
    }
    private fun importMarkdown() { if(editable()) { pickerActive=true; startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply { type="*/*"; addCategory(Intent.CATEGORY_OPENABLE) },102) } }
    private fun settings() {
        selected=null; base("설정","내 자료와 연결을 관리하세요")
        val content=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
        root.addView(ScrollView(this).apply { addView(content) },LinearLayout.LayoutParams(-1,0,1f))
        content.addView(label("PC 연결",13f).apply { setTextColor(TomaStyle.muted) })
        content.addView(label("연결된 PC 작업 공간",21f))
        content.addView(label(state.optString("address"),13f))
        content.addView(button("동기화") { sync() },LinearLayout.LayoutParams(-1,-2).apply { topMargin=dp(16); bottomMargin=dp(12) })
        content.addView(button("MD 가져오기") { importMarkdown() },LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(12) })
        content.addView(button("PC 다시 연결") { unlocked=false; loginScreen() },LinearLayout.LayoutParams(-1,-2))
        content.addView(label("PC와 연결할 때 동기화 버튼을 누르세요.",13f).apply { setTextColor(TomaStyle.muted); setPadding(0,dp(24),0,0) })
        bottomNav("설정")
    }
    private var activeToast:Toast?=null
    private fun toast(text:String) { activeToast?.cancel(); activeToast=Toast.makeText(this,text,Toast.LENGTH_SHORT).also { it.show() } }
    private fun message(text:String) { AlertDialog.Builder(this).setMessage(text).setPositiveButton("확인",null).show() }
    private fun loginScreen() {
        selected=null
        base("토마 모바일","")
        val content=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
        root.addView(ScrollView(this).apply { addView(content) },LinearLayout.LayoutParams(-1,0,1f))
        content.addView(label("생각을 담고,\n어디서나 이어가세요.",30f).apply { typeface=android.graphics.Typeface.create("sans-serif-medium",android.graphics.Typeface.NORMAL); setPadding(0,dp(12),0,dp(8)) })
        content.addView(label("PC에서 휴대폰연결을 누른 뒤 QR만 인식하세요.\n아이디·비밀번호·인증서 입력 없이 바로 연결됩니다.",14f).apply { setTextColor(TomaStyle.muted); setPadding(0,0,0,dp(24)) })
        qrResultHandler={ raw -> pairFromQr(raw) }
        content.addView(button("PC QR 스캔") {
            val options=GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
            GmsBarcodeScanning.getClient(this,options).startScan()
                .addOnSuccessListener { barcode -> pairFromQr(barcode.rawValue ?: "") }
                .addOnFailureListener { message("QR 스캐너를 열지 못했습니다. 갤러리 QR 사진 선택을 사용하세요.") }
        },LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(12) })
        content.addView(button("갤러리 QR 사진 선택") {
            pickerActive=true
            try {
                startActivityForResult(Intent(Intent.ACTION_GET_CONTENT).apply {
                    type="image/*"; addCategory(Intent.CATEGORY_OPENABLE)
                },104)
            } catch(e:Exception) {
                pickerActive=false
                message("사진 선택창을 열지 못했습니다: ${e.message ?: "지원 앱 없음"}")
            }
        },LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(12) })
        if(state.optBoolean("paired")) content.addView(primary(button("연결된 메모 열기") { unlocked=true; home(); sync() }))
        content.addView(label("기본 카메라가 토마 앱 열기를 제안하면 선택하세요. 열리지 않으면 위의 QR 스캔 또는 갤러리 사진 선택을 사용하면 됩니다.",12f).apply { setTextColor(TomaStyle.muted); setPadding(0,dp(24),0,dp(16)) })
    }
    private fun pairFromQr(raw:String) {
        val pairing=try { Pairing.parse(raw) }
        catch(e:IllegalArgumentException) { message(e.message ?: "토마데스크 연결 QR이 아닙니다."); return }
        background("PC에 연결 중…",{ Api(pairing.address).post("/pair",JSONObject().put("device",Build.MODEL)) }) { result ->
            state.put("address",pairing.address).put("paired",true).put("server_id",result.optString("server_id"))
            state.remove("pin"); state.remove("username"); state.remove("token")
            save(); unlocked=true; home(); sync()
        }
    }
    private fun background(status:String,job:()->JSONObject,done:(JSONObject)->Unit) {
        if(work)return; work=true; documentInput?.isEnabled=false; toast(status)
        executor.execute {
            try { val result=job(); runOnUiThread { work=false; documentInput?.isEnabled=!state.optBoolean("uncertain"); done(result) } }
            catch(e:Exception) { runOnUiThread { work=false; documentInput?.isEnabled=!state.optBoolean("uncertain"); message("${e.message ?: "연결 실패"}\n모바일에 저장한 변경 내용은 유지됩니다.") } }
        }
    }
    private fun home() {
        if(!unlocked) { loginScreen(); return }
        selected=null
        base("내 메모","생각이 머무는 작은 공간")
        val status=LinearLayout(this).apply { gravity=Gravity.CENTER_VERTICAL; background=TomaStyle.surface(this@MainActivity,TomaStyle.sage,16); setPadding(dp(14),0,dp(4),0) }
        val pending=arr("changes").length()
        status.addView(label(if(pending>0) "전송 대기 ${pending}개" else "${arr("notes").length()}개의 메모 · 내 기기에 저장됨",12f).apply { setTextColor(green) },LinearLayout.LayoutParams(0,-2,1f))
        status.addView(iconButton("sync","동기화") { sync() }.apply { background=TomaStyle.touch(this@MainActivity,TomaStyle.sage,16) },LinearLayout.LayoutParams(dp(48),dp(48))); root.addView(status,LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(20) })
        val search=field("메모 검색").apply { val icon=TomaStyle.icon("search",TomaStyle.muted); icon.setBounds(0,0,dp(20),dp(20)); setCompoundDrawables(icon,null,null,null); compoundDrawablePadding=dp(10) }; root.addView(search)
        root.addView(label("모든 메모",12f).apply { setTextColor(TomaStyle.muted); setPadding(0,dp(4),0,dp(12)) })
        val frame=FrameLayout(this)
        val list=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(0,0,0,dp(88)) }
        frame.addView(ScrollView(this).apply { isVerticalScrollBarEnabled=false; addView(list) },FrameLayout.LayoutParams(-1,-1))
        frame.addView(primary(button("＋ 새 메모") { if(editable())newNote() }).apply { elevation=dp(4).toFloat() },FrameLayout.LayoutParams(-2,dp(54),Gravity.BOTTOM or Gravity.END).apply { bottomMargin=dp(10); marginEnd=dp(4) })
        root.addView(frame,LinearLayout.LayoutParams(-1,0,1f)); bottomNav("메모")
        fun render(q:String) {
            list.removeAllViews()
            for(i in 0 until arr("notes").length()) {
                val n=arr("notes").getJSONObject(i)
                if(!(n.optString("title")+n.optString("markdown")+n.optJSONArray("blocks").toString()).contains(q,true))continue
                val card=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(dp(18),dp(14),dp(18),dp(14)); background=TomaStyle.touch(this@MainActivity); isFocusable=true }
                card.addView(label((if(n.optInt("pinned")==1) "★  " else "")+n.optString("title"),18f).apply { typeface=android.graphics.Typeface.create("sans-serif-medium",android.graphics.Typeface.NORMAL); maxLines=2; ellipsize=TextUtils.TruncateAt.END })
                val parts=n.optJSONArray("blocks") ?: JSONArray()
                card.addView(label((if(n.has("markdown")) n.optString("markdown").take(120) else if(parts.length()>0) parts.getJSONObject(0).optString("text").take(120) else "첫 문장을 적어보세요."),14f).apply { setTextColor(TomaStyle.muted); maxLines=2; ellipsize=TextUtils.TruncateAt.END })
                val updated=displayDate(n.optString("updated_at"))
                card.addView(label(if(updated.isNotBlank())updated else "${parts.length()}개의 블록",11f).apply { setTextColor(TomaStyle.muted); setPadding(0,dp(12),0,0) })
                card.setOnClickListener { if(!work) openNote(n) }
                list.addView(card,LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(12) })
            }
            if(list.childCount==0) {
                list.addView(mascot(76),LinearLayout.LayoutParams(dp(76),dp(76)).apply { gravity=Gravity.CENTER_HORIZONTAL; topMargin=dp(36) })
                list.addView(label(if(q.isBlank())"어떤 생각을 담아볼까요?" else "검색 결과가 없어요",20f).apply { gravity=Gravity.CENTER; setPadding(0,dp(16),0,dp(6)) })
                list.addView(label(if(q.isBlank())"새 메모를 쓰거나 PC의 메모를 가져오세요." else "다른 단어로 찾아보세요.",13f).apply { gravity=Gravity.CENTER; setTextColor(TomaStyle.muted) })
            }
        }
        render(""); search.addTextChangedListener(watcher { render(it) })
    }
    private fun watcher(action:(String)->Unit)=object:TextWatcher {
        override fun beforeTextChanged(s:CharSequence?,start:Int,count:Int,after:Int){}
        override fun onTextChanged(s:CharSequence?,start:Int,before:Int,count:Int) { action(s.toString()) }
        override fun afterTextChanged(s:Editable?){}
    }
    private fun change(note:JSONObject):JSONObject {
        val changes=arr("changes")
        for(i in 0 until changes.length()) if(changes.getJSONObject(i).getString("sync_id")==note.getString("sync_id")) return changes.getJSONObject(i)
        val c=JSONObject().put("op_id",UUID.randomUUID().toString()).put("sync_id",note.getString("sync_id"))
            .put("new",note.optBoolean("new")).put("base_revision",note.optInt("revision"))
            .put("base_hash",note.optString("base_hash")).put("base_content",note.optString("base_content"))
            .put("attachments",note.optJSONArray("attachments") ?: JSONArray()).put("title",note.optString("title"))
            .put("edits",JSONArray()).put("additions",JSONArray())
        changes.put(c); return c
    }
    private fun editBlock(note:JSONObject,block:JSONObject,text:String,closed:Boolean?=null) {
        val c=change(note)
        // A failed request may have reached the PC. Keep its op immutable until retry;
        // edits are blocked when any request has uncertain acknowledgement.
        if(block.has("addition")) {
            val added=c.getJSONArray("additions").getJSONObject(block.getInt("addition")).put("text",text)
            if(closed!=null)added.put("closed",closed)
        }
        else {
            val edits=c.getJSONArray("edits"); var found:JSONObject?=null
            for(i in 0 until edits.length()) if(edits.getJSONObject(i).getString("id")==block.getString("id"))found=edits.getJSONObject(i)
            val e=found ?: JSONObject().put("id",block.getString("id")).also { edits.put(it) }
            e.put("text",text); if(closed!=null)e.put("closed",closed)
        }
        block.put("text",text); if(closed!=null)block.put("closed",closed)
        save()
    }
    private fun editable():Boolean {
        if(work) { toast("동기화 중에는 잠시 기다려 주세요."); return false }
        if(state.optBoolean("uncertain")) { message("이전 동기화 응답을 받지 못했습니다. 먼저 다시 동기화해 전송 상태를 확인하세요. 메모는 보존돼 있습니다."); return false }
        return true
    }
    private fun openNote(note:JSONObject) {
        selected=note
        base("","")
        root.removeViewAt(0)
        val tools=LinearLayout(this).apply { gravity=Gravity.CENTER_VERTICAL }
        tools.addView(iconButton("back","목록") { home() },LinearLayout.LayoutParams(dp(48),dp(48)))
        tools.addView(label("내 메모",13f).apply { setTextColor(TomaStyle.muted) },LinearLayout.LayoutParams(0,-2,1f))
        tools.addView(iconButton("sync","동기화") { sync() },LinearLayout.LayoutParams(dp(48),dp(48)))
        val more=iconButton("more","더보기") { }
        more.setOnClickListener { if(!work)PopupMenu(this,more).apply {
            menu.add("MD 내보내기"); setOnMenuItemClickListener {
                pickerActive=true
                startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply { type="text/markdown"; addCategory(Intent.CATEGORY_OPENABLE); putExtra(Intent.EXTRA_TITLE,note.optString("title")+".md") },103); true
            }; show()
        } }; tools.addView(more,LinearLayout.LayoutParams(dp(48),dp(48))); root.addView(tools)
        val title=label(note.optString("title"),30f).apply { typeface=android.graphics.Typeface.create("sans-serif-medium",android.graphics.Typeface.NORMAL); setPadding(0,dp(24),0,dp(8)); contentDescription="메모 제목 변경"; maxLines=3; ellipsize=TextUtils.TruncateAt.END }
        title.setOnClickListener {
            if(editable()) { val input=field("제목",note.optString("title")); AlertDialog.Builder(this).setTitle("제목 변경").setView(input).setPositiveButton("저장") { _,_ ->
                note.put("title",input.text.toString()); change(note).put("title",input.text.toString()); save(); openNote(note)
            }.setNegativeButton("취소",null).show() }
        }; root.addView(title)
        val hint=label(if(!note.optBoolean("new") && !note.optBoolean("markdown_native"))"첫 Markdown 저장 시 PC에 원본 사본을 보관합니다" else "문서 전체를 Markdown으로 편집하세요",11f).apply { setTextColor(TomaStyle.muted); setPadding(0,0,0,dp(8)) }; root.addView(hint)
        val tabs=LinearLayout(this)
        val host=FrameLayout(this)
        fun showEditor() {
            flushDraft(); host.removeAllViews()
            val input=EditText(this).apply {
                this.hint="# 제목\n\n자유롭게 기록해보세요.\n- [ ] 할 일\n**굵게** · `코드`"
                contentDescription="Markdown 문서"; textSize=16f; setTextColor(ink); setHintTextColor(TomaStyle.muted)
                setSingleLine(false); gravity=Gravity.TOP; background=TomaStyle.surface(this@MainActivity)
                setPadding(dp(16),dp(16),dp(16),dp(16)); setLineSpacing(dp(5).toFloat(),1.1f)
                inputType=android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE or android.text.InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
                setText(markdownSource(note)); isEnabled=!work && !state.optBoolean("uncertain")
                filters=arrayOf(InputFilter { inserted,start,end,dest,dstart,dend ->
                    val candidate=dest.subSequence(0,dstart).toString()+inserted.subSequence(start,end)+dest.subSequence(dend,dest.length)
                    if(end>start && (candidate.toByteArray(Charsets.UTF_8).size>1_000_000 || candidate.count { it=='\n' }>10000)) {
                        toast("Markdown 문서는 1MB, 10,000줄까지 지원합니다."); dest.subSequence(dstart,dend)
                    } else null
                })
                addTextChangedListener(watcher { source ->
                    note.put("markdown",source)
                    val c=change(note); c.put("markdown",source); c.remove("edits"); c.remove("additions")
                    draftPending=true; draftHandler.removeCallbacks(writeDraft); draftHandler.postDelayed(writeDraft,350)
                })
            }
            documentInput=input; host.addView(input,FrameLayout.LayoutParams(-1,-1))
        }
        tabs.addView(button("편집") { showEditor() },LinearLayout.LayoutParams(0,dp(44),1f).apply { marginEnd=dp(6) })
        tabs.addView(button("미리보기") {
            flushDraft(); documentInput?.clearFocus(); (getSystemService(INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager).hideSoftInputFromWindow(host.windowToken,0)
            documentInput=null; host.removeAllViews()
            val content=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(dp(8),dp(12),dp(8),dp(24)) }
            host.addView(ScrollView(this).apply { addView(content) },FrameLayout.LayoutParams(-1,-1)); renderMarkdown(note,content)
        },LinearLayout.LayoutParams(0,dp(44),1f))
        root.addView(tabs,LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(12) }); root.addView(host,LinearLayout.LayoutParams(-1,0,1f))
        showEditor()
    }
    private fun markdownSource(note:JSONObject):String {
        val pending=(0 until arr("changes").length()).map { arr("changes").getJSONObject(it) }.firstOrNull { it.optString("sync_id")==note.optString("sync_id") }
        if(pending?.has("markdown")==true)return pending.getString("markdown")
        val legacy=(pending?.optJSONArray("edits")?.length() ?: 0)>0 || (pending?.optJSONArray("additions")?.length() ?: 0)>0
        if(note.has("markdown") && !legacy)return note.optString("markdown")
        val blocks=note.optJSONArray("blocks") ?: JSONArray()
        return (0 until blocks.length()).joinToString("\n\n") { i ->
            val b=blocks.getJSONObject(i); val text=b.optString("text").replace("☐ ","- [ ] ").replace("☑ ","- [x] ").replace("• ","- ")
            val heading=b.optInt("level").coerceIn(0,6)
            if(heading>0)"#".repeat(heading)+" "+text else "  ".repeat(b.optInt("indent").coerceIn(0,12))+text
        }
    }
    private fun renderMarkdown(note:JSONObject,pane:LinearLayout) {
        pane.removeAllViews(); var hiddenLevel:Int?=null
        val sections=MarkdownSections.split(markdownSource(note))
        sections.forEachIndexed { index,section ->
            if(hiddenLevel!=null) { if(section.level>0 && section.level<=hiddenLevel!!)hiddenLevel=null else return@forEachIndexed }
            val key=note.optString("sync_id")+":"+index; val closed=folded.contains(key)
            if(section.level>0) {
                val row=LinearLayout(this).apply { gravity=Gravity.CENTER_VERTICAL }
                row.addView(button(if(closed)"▸" else "▾") { if(closed)folded.remove(key) else folded.add(key); renderMarkdown(note,pane) }.apply { contentDescription=if(closed)"펼치기" else "접기"; setPadding(0,0,0,0); background=TomaStyle.touch(this@MainActivity,TomaStyle.paper,12) },LinearLayout.LayoutParams(dp(48),dp(48)))
                row.addView(label("",20f).apply { markwon.setMarkdown(this,section.heading); movementMethod=null },LinearLayout.LayoutParams(0,-2,1f)); pane.addView(row)
            }
            if(closed && section.level>0)hiddenLevel=section.level
            else if(section.body.isNotBlank())pane.addView(label("",16f).apply { setTextIsSelectable(true); markwon.setMarkdown(this,section.body); movementMethod=null })
        }
        val attachments=note.optJSONArray("attachments") ?: JSONArray()
        if(attachments.length()>0)pane.addView(label("PC 첨부 이미지 · 원본 보관",12f).apply { setTextColor(TomaStyle.muted) })
        for(i in 0 until attachments.length())try {
            val a=attachments.getJSONObject(i); if(!a.optString("mime_type").startsWith("image/"))continue
            val bytes=android.util.Base64.decode(a.getString("data_base64"),0)
            val options=BitmapFactory.Options().apply { inJustDecodeBounds=true }; BitmapFactory.decodeByteArray(bytes,0,bytes.size,options)
            options.inSampleSize=1; while(options.outWidth/options.inSampleSize>1600 || options.outHeight/options.inSampleSize>1600)options.inSampleSize*=2
            options.inJustDecodeBounds=false
            BitmapFactory.decodeByteArray(bytes,0,bytes.size,options)?.let { bmp -> pane.addView(ImageView(this).apply { setImageBitmap(bmp); adjustViewBounds=true; contentDescription="PC 첨부 이미지" },LinearLayout.LayoutParams(-1,-2)) }
        } catch(_:Exception) { pane.addView(label("첨부 이미지는 PC에서 확인하세요.",12f)) }
    }
    private fun newNote(title:String="새 메모"):JSONObject {
        val n=JSONObject().put("sync_id",UUID.randomUUID().toString()).put("new",true).put("title",title).put("blocks",JSONArray()).put("markdown","")
        arr("notes").put(n); change(n); save(); openNote(n); return n
    }
    private fun sync() {
        flushDraft()
        if((0 until arr("changes").length()).any { arr("changes").getJSONObject(it).has("markdown") }) {
            val api=Api(state.optString("address"))
            background("PC 버전 확인 중…",{ api.post("/sync",JSONObject().put("changes",JSONArray()).put("server_id",state.optString("server_id"))) }) { probe ->
                val caps=probe.optJSONArray("capabilities") ?: JSONArray()
                if(!(0 until caps.length()).any { caps.optString(it)=="markdown_document_v1" }) {
                    message("Markdown 동기화에는 PC 토마데스크 0.1.2 이상이 필요합니다. 문서는 휴대폰에 보관되어 있습니다.")
                } else performSync()
            }
        } else performSync()
    }
    private fun performSync() {
        flushDraft()
        val changes=JSONArray(arr("changes").toString())
        if(changes.length()>0) { state.put("uncertain",true); save() }
        val api=Api(state.optString("address"))
        val request=JSONObject().put("changes",changes).put("server_id",state.optString("server_id"))
        background("PC와 동기화 중…",{ api.post("/sync",request) }) { result ->
            if(state.has("server_id") && state.getString("server_id")!=result.getString("server_id")) {
                message("PC의 데이터 저장소가 변경되었습니다. 기존 모바일 자료는 보존했습니다."); return@background
            }
            state.put("server_id",result.getString("server_id")).put("notes",result.getJSONArray("notes")).put("schedules",result.getJSONArray("schedules"))
                .put("changes",JSONArray()).put("uncertain",false)
            save(); if(unlocked)home() else loginScreen()
            val r=result.getJSONArray("results"); var conflicts=0
            for(i in 0 until r.length())if(r.getJSONObject(i).optBoolean("conflict"))conflicts++
            toast(if(conflicts>0)"동기화 완료 · 충돌 사본 ${conflicts}개 보관" else "동기화 완료")
        }
    }
    private fun displayDate(raw:String):String {
        if(raw.matches(Regex("[0-9]{12,14}")))return "${raw.substring(0,4)}.${raw.substring(4,6)}.${raw.substring(6,8)} · ${raw.substring(8,10)}:${raw.substring(10,12)}"
        return raw.take(16).replace("T"," ")
    }
    private fun agendaCard(title:String,detail:String):LinearLayout = LinearLayout(this).apply {
        orientation=LinearLayout.VERTICAL; setPadding(dp(18),dp(14),dp(18),dp(14)); background=TomaStyle.surface(this@MainActivity)
        addView(label(title,18f).apply { typeface=android.graphics.Typeface.create("sans-serif-medium",android.graphics.Typeface.NORMAL) })
        addView(label(detail,13f).apply { setTextColor(TomaStyle.muted) })
        layoutParams=LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(12) }
    }
    private fun agenda() {
        selected=null
        base("일정과 D-Day","다가오는 날들을 한눈에 · 편집은 PC에서")
        val list=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }; root.addView(ScrollView(this).apply { addView(list) },LinearLayout.LayoutParams(-1,0,1f))
        for(i in 0 until arr("notes").length()) { val n=arr("notes").getJSONObject(i); if(n.optString("d_day_at").isNotEmpty())list.addView(agendaCard(n.optString("title"),"D-Day · "+displayDate(n.optString("d_day_at")))) }
        for(i in 0 until arr("schedules").length()) { val s=arr("schedules").getJSONObject(i); list.addView(agendaCard(s.optString("title"),displayDate(s.optString("start_at"))+" ~ "+displayDate(s.optString("end_at")))) }
        if(list.childCount==0) {
            list.addView(mascot(76),LinearLayout.LayoutParams(dp(76),dp(76)).apply { gravity=Gravity.CENTER_HORIZONTAL; topMargin=dp(48) })
            list.addView(label("아직 예정된 일정이 없어요",19f).apply { gravity=Gravity.CENTER; setPadding(0,dp(20),0,dp(8)) })
            list.addView(label("PC에서 일정을 만들고 동기화해보세요.",13f).apply { gravity=Gravity.CENTER; setTextColor(TomaStyle.muted) })
        }
        bottomNav("일정")
    }
    override fun onActivityResult(request:Int,result:Int,data:Intent?) {
        super.onActivityResult(request,result,data)
        if(!pickerActive)return
        pickerActive=false
        if(result!=RESULT_OK) { if(!unlocked && request!=104)loginScreen(); return }
        if(request==101) { unlocked=true; home(); return }
        if(request==104) {
            val uri=data?.data ?: run { message("QR 사진을 선택하지 못했습니다."); return }
            executor.execute {
                try {
                    val image=InputImage.fromFilePath(this,uri)
                    val options=BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
                    val scanner=BarcodeScanning.getClient(options)
                    scanner.process(image)
                        .addOnSuccessListener { barcodes ->
                            val raw=barcodes.firstOrNull { it.format==Barcode.FORMAT_QR_CODE && !it.rawValue.isNullOrBlank() }?.rawValue
                            if(raw==null) message("사진에서 QR 코드를 찾지 못했습니다. QR이 선명하게 보이는 사진을 선택하세요.")
                            else qrResultHandler?.invoke(raw)
                        }
                        .addOnFailureListener { message("QR 사진을 읽지 못했습니다: ${it.message ?: "이미지 오류"}") }
                        .addOnCompleteListener { scanner.close() }
                } catch(e:Exception) { runOnUiThread { message("QR 사진을 열지 못했습니다: ${e.message ?: "이미지 오류"}") } }
            }
            return
        }
        // Document picker returns to the same trusted activity; it is not an unlock path.
        if(request==102 || request==103) {
            unlocked=true
            try {
                if(request==102 && editable()) {
                    val text=contentResolver.openInputStream(data!!.data!!)?.use { input ->
                        val out=java.io.ByteArrayOutputStream(); val buffer=ByteArray(4096)
                        while(true) { val n=input.read(buffer); if(n<0)break; require(out.size()+n<=1_000_000) { "Markdown 파일은 1MB까지 지원합니다." }; out.write(buffer,0,n) }
                        out.toString("UTF-8")
                    } ?: ""
                    require(text.toByteArray().size<=1_000_000) { "Markdown 파일은 1MB까지 지원합니다." }
                    val n=newNote("가져온 Markdown"); n.put("markdown",text); change(n).put("markdown",text); save(); openNote(n)
                } else if(request==103) {
                    flushDraft(); val n=selected ?: return
                    val md=markdownSource(n)
                    contentResolver.openOutputStream(data!!.data!!)?.use { it.write(md.toByteArray(Charsets.UTF_8)) }; toast("Markdown 원문을 내보냈습니다."); openNote(n)
                }
            } catch(e:Exception) { message(e.message ?: "파일 처리 실패") }
        }
    }
    override fun onBackPressed() { if(work)return; if(selected!=null && unlocked)home() else super.onBackPressed() }
}

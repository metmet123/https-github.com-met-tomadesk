package com.toma.companion

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.*
import android.graphics.drawable.*

/** Shared native surfaces and a small, consistent line icon family. */
object TomaStyle {
    val paper = Color.rgb(249,248,244)
    val ink = Color.rgb(35,49,43)
    val green = Color.rgb(44,101,76)
    val muted = Color.rgb(115,124,116)
    val sage = Color.rgb(232,239,230)
    val line = Color.rgb(228,231,221)
    fun surface(context: Context, color: Int = Color.WHITE, radius: Int = 18, border: Boolean = false): GradientDrawable =
        GradientDrawable().apply {
            setColor(color); cornerRadius = radius * context.resources.displayMetrics.density
            if (border) setStroke((context.resources.displayMetrics.density + .5f).toInt(), line)
        }
    fun touch(context: Context, color: Int = Color.WHITE, radius: Int = 18): RippleDrawable =
        RippleDrawable(ColorStateList.valueOf(0x1834654C), surface(context,color,radius), null)
    fun icon(name: String, color: Int = green): Drawable = object: Drawable() {
        private val p=Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color=color; style=Paint.Style.STROKE; strokeWidth=1.7f; strokeCap=Paint.Cap.ROUND; strokeJoin=Paint.Join.ROUND }
        override fun draw(canvas: Canvas) {
            canvas.save(); canvas.translate(bounds.left.toFloat(),bounds.top.toFloat()); canvas.scale(bounds.width()/24f,bounds.height()/24f)
            fun line(a:Float,b:Float,c:Float,d:Float)=canvas.drawLine(a,b,c,d,p)
            when(name) {
                "search" -> { canvas.drawCircle(10.5f,10.5f,6f,p); line(15f,15f,20f,20f) }
                "plus" -> { line(12f,5f,12f,19f); line(5f,12f,19f,12f) }
                "back" -> { line(19f,12f,5f,12f); line(5f,12f,11f,6f); line(5f,12f,11f,18f) }
                "more" -> { p.style=Paint.Style.FILL; for(x in listOf(5f,12f,19f))canvas.drawCircle(x,12f,1.5f,p); p.style=Paint.Style.STROKE }
                "sync" -> { canvas.drawArc(4f,4f,20f,20f,210f,150f,false,p); canvas.drawArc(4f,4f,20f,20f,30f,150f,false,p); line(20f,7f,20f,12f); line(15f,12f,20f,12f); line(4f,12f,9f,12f); line(4f,12f,4f,17f) }
                "calendar" -> { canvas.drawRoundRect(4f,5f,20f,21f,3f,3f,p); line(4f,10f,20f,10f); line(8f,3f,8f,7f); line(16f,3f,16f,7f); line(8f,14f,10f,14f); line(14f,14f,16f,14f) }
                "settings" -> { for(y in listOf(6f,12f,18f))line(4f,y,20f,y); canvas.drawCircle(9f,6f,2f,p); canvas.drawCircle(15f,12f,2f,p); canvas.drawCircle(9f,18f,2f,p) }
                "lock" -> { canvas.drawRoundRect(5f,10f,19f,21f,3f,3f,p); canvas.drawArc(8f,3f,16f,15f,180f,180f,false,p); line(12f,14f,12f,17f) }
                else -> { canvas.drawRoundRect(5f,3f,19f,21f,3f,3f,p); line(9f,8f,15f,8f); line(9f,12f,15f,12f); line(9f,16f,13f,16f) }
            }
            canvas.restore()
        }
        override fun setAlpha(alpha:Int) { p.alpha=alpha }
        override fun setColorFilter(filter:ColorFilter?) { p.colorFilter=filter }
        @Deprecated("Deprecated in Android") override fun getOpacity()=PixelFormat.TRANSLUCENT
    }
}

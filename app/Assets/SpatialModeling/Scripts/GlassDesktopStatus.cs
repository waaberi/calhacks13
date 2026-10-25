using System;
using UnityEngine;

namespace SpatialModeling
{
    // Monitor-only emergency fallback when the world-space screen is absent.
    public static class GlassDesktopStatus
    {
        static Texture2D texture;
        static GUIStyle panel,button,entry;
        static void Ensure()
        {
            if(texture==null)
            {
                texture=new Texture2D(64,64,TextureFormat.RGBA32,false){name="Rounded fallback status",hideFlags=HideFlags.HideAndDontSave};
                for(int y=0;y<64;y++)for(int x=0;x<64;x++)texture.SetPixel(x,y,RoundedGlassImage.Contains(new Rect(0,0,64,64),new Vector2(x+.5f,y+.5f),18)?Color.white:Color.clear);
                texture.Apply();
                panel=new GUIStyle(GUI.skin.box){fontSize=26,alignment=TextAnchor.UpperLeft,padding=new RectOffset(24,24,18,18),border=new RectOffset(24,24,24,24)};
                panel.normal.background=texture;panel.normal.textColor=GlassTheme.Ink;
                button=new GUIStyle(GUI.skin.button){fontSize=22,border=new RectOffset(24,24,24,24)};button.normal.background=button.hover.background=button.active.background=texture;
            }
        }
        public static string TextEntry(Rect rect,string value)
        {
            Ensure();
            if(entry==null){entry=new GUIStyle(GUI.skin.textField){fontSize=22,border=new RectOffset(24,24,24,24),padding=new RectOffset(12,12,4,4)};entry.normal.background=entry.focused.background=texture;entry.normal.textColor=entry.focused.textColor=GlassTheme.Ink;}
            var before=GUI.backgroundColor;GUI.backgroundColor=GlassTheme.Control;
            string result=GUI.TextField(rect,value,entry);GUI.backgroundColor=before;return result;
        }
        public static void Draw(string text,bool error,Action recenter)
        {
            Ensure();
            float scale=GlassTheme.TextScale;panel.fontSize=Mathf.RoundToInt(26*scale);button.fontSize=Mathf.RoundToInt(22*scale);
            var before=GUI.backgroundColor;GUI.backgroundColor=error?GlassTheme.Error:GlassTheme.Surface;
            float height=190*scale;
            GUI.Box(new Rect(20,20,Mathf.Min(Screen.width-40,1400*scale),height),text,panel);
            var target=new Rect(20,36+height,Mathf.Min(Screen.width-40,370*scale),56*scale);
            bool inside=RoundedGlassImage.Contains(target,Event.current.mousePosition,18);
            GUI.backgroundColor=inside?(GUIUtility.hotControl!=0?new Color(.36f,.28f,.13f,1):GlassTheme.Hover):GlassTheme.Control;
            bool oldEnabled=GUI.enabled;
            if(Event.current.isMouse&&!inside)GUI.enabled=false;
            bool clicked=GUI.Button(target,"Recenter view (B / Y / R)",button);GUI.enabled=oldEnabled;
            if(clicked)recenter();
            GUI.backgroundColor=before;
        }
    }
}

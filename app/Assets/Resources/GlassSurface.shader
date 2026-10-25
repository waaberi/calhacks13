Shader "SpatialModeling/GlassSurface"
{
    Properties
    {
        [PerRendererData] _MainTex("Sprite",2D)="white"{}
        _Frost("Scene diffusion",Range(0,1))=1
        _Refraction("Edge refraction",Range(0,1))=1
        _StencilComp("Stencil Comparison",Float)=8
        _Stencil("Stencil ID",Float)=0
        _StencilOp("Stencil Operation",Float)=0
        _StencilWriteMask("Stencil Write Mask",Float)=255
        _StencilReadMask("Stencil Read Mask",Float)=255
        _ColorMask("Color Mask",Float)=15
        [Toggle(UNITY_UI_ALPHACLIP)] _UseUIAlphaClip("Alpha Clip",Float)=0
    }
    SubShader
    {
        Tags {"Queue"="Transparent" "RenderType"="Transparent" "IgnoreProjector"="True" "CanUseSpriteAtlas"="True"}
        Stencil {Ref [_Stencil] Comp [_StencilComp] Pass [_StencilOp] ReadMask [_StencilReadMask] WriteMask [_StencilWriteMask]}
        Cull Off ZWrite Off ZTest [unity_GUIZTestMode]
        Blend One OneMinusSrcAlpha
        ColorMask [_ColorMask]
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma target 3.5
            #pragma multi_compile_instancing
            #pragma multi_compile_local _ UNITY_UI_CLIP_RECT
            #pragma multi_compile_local _ UNITY_UI_ALPHACLIP
            #include "UnityCG.cginc"
            #include "UnityUI.cginc"
            struct appdata
            {
                float4 vertex:POSITION;float4 color:COLOR;float2 uv:TEXCOORD0;float4 shape:TEXCOORD1;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };
            struct v2f
            {
                float4 vertex:SV_POSITION;float4 color:COLOR;float2 uv:TEXCOORD0;float4 shape:TEXCOORD1;
                float4 screen:TEXCOORD2;float4 local:TEXCOORD3;float3 view:TEXCOORD4;
                UNITY_VERTEX_OUTPUT_STEREO
            };
            UNITY_DECLARE_SCREENSPACE_TEXTURE(_GlassBackdrop);
            UNITY_DECLARE_SCREENSPACE_TEXTURE(_GlassSharpBackdrop);
            float _Frost,_Refraction;
            float4 _ClipRect;
            v2f vert(appdata v)
            {
                v2f o;UNITY_SETUP_INSTANCE_ID(v);UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.local=v.vertex;o.vertex=UnityObjectToClipPos(v.vertex);o.screen=ComputeScreenPos(o.vertex);
                o.color=v.color;o.uv=v.uv;o.shape=v.shape;
                o.view=ObjSpaceViewDir(v.vertex);return o;
            }
            half4 frag(v2f i):SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float2 size=max(i.shape.xy,1),p=(i.uv-.5)*size;
                float radius=max(i.shape.z,1);
                float2 q=abs(p)-(size*.5-radius);
                float distance=length(max(q,0))+min(max(q.x,q.y),0)-radius;
                float edge=saturate(1+distance/(i.shape.w>.5?18:10));
                float2 n=normalize(max(q,0)+.0001)*sign(p);
                if(max(q.x,q.y)<0)n=q.x>q.y?float2(sign(p.x),0):float2(0,sign(p.y));
                float2 screenUV=i.screen.xy/i.screen.w;
                // Project the rounded bevel normal using screen derivatives: follows curved/yawed panels.
                float2 sx=ddx(screenUV),sy=ddy(screenUV);
                float2 localX=ddx(p),localY=ddy(p);
                float determinant=localX.x*localY.y-localX.y*localY.x;
                float2 dx=(sx*localY.y-sy*localX.y)/(abs(determinant)>.00001?determinant:1);
                float2 dy=(-sx*localY.x+sy*localX.x)/(abs(determinant)>.00001?determinant:1);
                float3 incident=normalize(float3(-i.view.xy,-abs(i.view.z)));
                float3 bevelNormal=normalize(float3(n*edge*.85,1-edge*.55));
                float3 bent=refract(incident,bevelNormal,1.0/1.45);
                float3 flat=refract(incident,float3(0,0,1),1.0/1.45);
                float2 displacement=clamp((bent.xy/max(abs(bent.z),.2)-flat.xy/max(abs(flat.z),.2))*10,-8,8)*_Refraction;
                float2 refractedUV=saturate(screenUV+dx*displacement.x+dy*displacement.y);
                half4 backdrop=UNITY_SAMPLE_SCREENSPACE_TEXTURE(_GlassBackdrop,refractedUV);
                half4 sharp=UNITY_SAMPLE_SCREENSPACE_TEXTURE(_GlassSharpBackdrop,refractedUV);
                backdrop=lerp(sharp,backdrop,saturate(_Frost-edge*.35));
                float opaque=step(i.shape.w,-.5);
                float facing=abs(normalize(i.view).z);
                float fresnel=.04+.96*pow(1-facing,5);
                float light=dot(n,normalize(float2(-.6,.8)));
                float rim=exp(-abs(distance+1.1)*1.5);
                float inner=exp(-abs(distance+3.5)*.5);
                // Two broad, restrained reflected softboxes, plus a bevel caustic on the opposite edge.
                float reflection=pow(saturate(i.uv.y*.75+(1-i.uv.x)*.25),6)*.055;
                float3 tint=i.color.rgb;
                float3 fallback=tint+reflection+edge*fresnel*.12;
                float3 transmitted=backdrop.rgb*.36+tint*.68+reflection;
                float3 rgb=lerp(fallback,transmitted,backdrop.a*(1-opaque));
                rgb+=rim*(.07+.35*pow(abs(light),5))*(i.shape.w>1.5?1.65:1)+inner*pow(saturate(-light),8)*.075;
                float alpha=lerp(i.color.a,1,backdrop.a*(1-opaque));
                alpha=lerp(alpha,1,opaque);
                float coverage=saturate(-distance/max(fwidth(distance),.5)+.5);
                #ifdef UNITY_UI_CLIP_RECT
                coverage*=UnityGet2DClipping(i.local.xy,_ClipRect);
                #endif
                #ifdef UNITY_UI_ALPHACLIP
                clip(coverage-.001);
                #endif
                return half4(rgb*alpha,alpha)*coverage;
            }
            ENDCG
        }
    }
}

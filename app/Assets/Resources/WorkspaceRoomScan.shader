Shader "SpatialModeling/MetaRoomScan"
{
    Properties { _VertexBarycentric("MRUK vertex barycentric", Float)=0 _WireAmount("Wire amount", Float)=1 }
    SubShader
    {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" "RenderPipeline"="UniversalPipeline" }
        Pass
        {
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            Cull Off
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile_instancing
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            float _VertexBarycentric, _WireAmount;
            struct A { float4 positionOS:POSITION; float2 bary:TEXCOORD1; float4 color:COLOR; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 positionCS:SV_POSITION; float2 bary:TEXCOORD0; UNITY_VERTEX_OUTPUT_STEREO };
            V Vert(A v) { V o; UNITY_SETUP_INSTANCE_ID(v); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o); o.positionCS=TransformObjectToHClip(v.positionOS.xyz);o.bary=lerp(v.bary,v.color.rg,_VertexBarycentric);return o; }
            half4 Frag(V v):SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(v);
                float3 bary=float3(v.bary,1-v.bary.x-v.bary.y);
                float3 edge=smoothstep(0,fwidth(bary)*1.5,bary);
                float wire=1-min(edge.x,min(edge.y,edge.z));
                return half4(.12,.8,1,lerp(.025,.6,wire*_WireAmount));
            }
            ENDHLSL
        }
    }
}

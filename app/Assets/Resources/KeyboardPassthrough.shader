// Selective compositor passthrough: no camera textures or buffers are sampled.
// Inspired by Meta SDK BuildingBlocks/PassthroughWindow/SelectivePassthrough.
Shader "SpatialModeling/Keyboard Passthrough Window"
{
    Properties { _Color("Overlay RGBA (zero reveals underlay)",Color)=(0,0,0,0) }
    SubShader
    {
        Tags { "RenderPipeline"="UniversalPipeline" "Queue"="Overlay+990" "RenderType"="Transparent" }
        Pass
        {
            Tags { "LightMode"="UniversalForward" }
            ZWrite Off
            ZTest Always
            Cull Off
            ColorMask RGBA
            Blend One Zero
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile_instancing
            #pragma multi_compile _ STEREO_INSTANCING_ON STEREO_MULTIVIEW_ON
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            struct A { float4 positionOS:POSITION; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 positionCS:SV_POSITION; UNITY_VERTEX_OUTPUT_STEREO };
            CBUFFER_START(UnityPerMaterial)
            half4 _Color;
            CBUFFER_END
            V Vert(A v) { V o; UNITY_SETUP_INSTANCE_ID(v); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o); o.positionCS=TransformObjectToHClip(v.positionOS.xyz); return o; }
            half4 Frag(V v):SV_Target { UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(v); return _Color; }
            ENDHLSL
        }
    }
}

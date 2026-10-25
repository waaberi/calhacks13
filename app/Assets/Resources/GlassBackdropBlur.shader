Shader "SpatialModeling/GlassBackdropBlur"
{
    SubShader
    {
        Tags { "RenderPipeline"="UniversalPipeline" }
        ZWrite Off ZTest Always Cull Off
        HLSLINCLUDE
        #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
        #include "Packages/com.unity.render-pipelines.core/Runtime/Utilities/Blit.hlsl"
        half4 Diffuse(Varyings input,float2 axis)
        {
            UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);
            float2 uv=input.texcoord;
            // Separable normalized Gaussian. RGBA remains intact; no forced opaque alpha.
            float2 stepUV=axis*_BlitTexture_TexelSize.xy*3;
            half4 c=SAMPLE_TEXTURE2D_X(_BlitTexture,sampler_LinearClamp,uv)*.227027;
            c+=SAMPLE_TEXTURE2D_X(_BlitTexture,sampler_LinearClamp,uv+stepUV*1.384615)*.316216;
            c+=SAMPLE_TEXTURE2D_X(_BlitTexture,sampler_LinearClamp,uv-stepUV*1.384615)*.316216;
            c+=SAMPLE_TEXTURE2D_X(_BlitTexture,sampler_LinearClamp,uv+stepUV*3.230769)*.070270;
            c+=SAMPLE_TEXTURE2D_X(_BlitTexture,sampler_LinearClamp,uv-stepUV*3.230769)*.070270;
            return c;
        }
        half4 Horizontal(Varyings i):SV_Target{return Diffuse(i,float2(1,0));}
        half4 Vertical(Varyings i):SV_Target{return Diffuse(i,float2(0,1));}
        half4 Copy(Varyings i):SV_Target
        {
            UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
            return SAMPLE_TEXTURE2D_X(_BlitTexture,sampler_LinearClamp,i.texcoord);
        }
        ENDHLSL
        Pass
        {
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Horizontal
            #pragma target 3.5
            #pragma multi_compile_instancing
            #pragma multi_compile _ STEREO_INSTANCING_ON STEREO_MULTIVIEW_ON
            ENDHLSL
        }
        Pass
        {
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Vertical
            #pragma target 3.5
            #pragma multi_compile_instancing
            #pragma multi_compile _ STEREO_INSTANCING_ON STEREO_MULTIVIEW_ON
            ENDHLSL
        }
        Pass
        {
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Copy
            #pragma target 3.5
            #pragma multi_compile_instancing
            #pragma multi_compile _ STEREO_INSTANCING_ON STEREO_MULTIVIEW_ON
            ENDHLSL
        }
    }
}

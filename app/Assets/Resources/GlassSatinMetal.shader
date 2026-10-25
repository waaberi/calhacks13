Shader "SpatialModeling/Glass Satin Metal"
{
    Properties { _BaseColor("Anodized metal",Color)=(.64,.46,.85,1) _Metallic("Metalness",Range(0,1))=.86 _Smoothness("Smoothness",Range(0,1))=.73 }
    SubShader
    {
        Tags { "RenderPipeline"="UniversalPipeline" "RenderType"="Opaque" "Queue"="Geometry" }
        Pass
        {
            Tags { "LightMode"="UniversalForward" }
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile_instancing
            #pragma multi_compile _ STEREO_INSTANCING_ON STEREO_MULTIVIEW_ON
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            struct Attributes { float4 positionOS:POSITION; float3 normalOS:NORMAL; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct Varyings { float4 positionCS:SV_POSITION; float3 normalWS:TEXCOORD0; float3 positionWS:TEXCOORD1; UNITY_VERTEX_OUTPUT_STEREO };
            CBUFFER_START(UnityPerMaterial)
            half4 _BaseColor;half _Metallic;half _Smoothness;
            CBUFFER_END
            Varyings Vert(Attributes input)
            {
                Varyings output;UNITY_SETUP_INSTANCE_ID(input);UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);
                output.positionWS=TransformObjectToWorld(input.positionOS.xyz);output.positionCS=TransformWorldToHClip(output.positionWS);
                output.normalWS=TransformObjectToWorldNormal(input.normalOS);return output;
            }
            half4 Frag(Varyings input):SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);
                float3 n=normalize(input.normalWS),v=GetWorldSpaceNormalizeViewDir(input.positionWS);
                // Stable broad studio environment highlights, no emissive rod/bloom.
                float3 light=normalize(float3(-.6,.85,-.4)),strip=normalize(float3(.65,.2,.7));
                float diffuse=.23+.45*saturate(dot(n,light))+.14*saturate(n.y);
                float exponent=lerp(12,110,_Smoothness);
                float spec=pow(saturate(dot(n,normalize(v+light))),exponent)*1.1
                    +pow(saturate(dot(n,normalize(v+strip))),exponent*.6)*.45;
                float fresnel=pow(1-saturate(dot(n,v)),4);
                float3 reflected=reflect(-v,n);
                float sky=.22+.32*smoothstep(-.6,.8,reflected.y);
                float stripWidth=lerp(.4,.12,_Smoothness);
                float studioStrip=exp(-pow((reflected.x+.28)/stripWidth,2))*smoothstep(-.5,.15,reflected.y)*.65;
                float3 metalTint=lerp(float3(.04,.04,.04),_BaseColor.rgb,_Metallic);
                float3 color=_BaseColor.rgb*diffuse*(1-_Metallic)+metalTint*(sky+studioStrip+spec+fresnel*.28);
                return half4(color,1);
            }
            ENDHLSL
        }
    }
}

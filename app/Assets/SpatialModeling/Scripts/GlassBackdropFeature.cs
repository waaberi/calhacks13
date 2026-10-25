using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.RenderGraphModule;
using UnityEngine.Rendering.Universal;

namespace SpatialModeling
{
    // Capture Unity color before UI, preserving RGBA and the camera's XR slices.
    // Compositor passthrough is deliberately not an input to this pass.
    public sealed class GlassBackdropFeature : ScriptableRendererFeature
    {
        Material blur;
        BackdropPass pass;
        public override void Create()
        {
            CoreUtils.Destroy(blur);
            var shader=Resources.Load<Shader>("GlassBackdropBlur");
            if(shader!=null)blur=CoreUtils.CreateEngineMaterial(shader);
            pass=new BackdropPass(blur){renderPassEvent=RenderPassEvent.BeforeRenderingTransparents};
        }
        public override void AddRenderPasses(ScriptableRenderer renderer,ref RenderingData data)
        {
            if(blur!=null && data.cameraData.cameraType!=CameraType.Preview)renderer.EnqueuePass(pass);
        }
        protected override void Dispose(bool disposing){CoreUtils.Destroy(blur);}
        sealed class BackdropPass : ScriptableRenderPass
        {
            readonly Material material;
            static readonly int TextureId=Shader.PropertyToID("_GlassBackdrop");
            static readonly int SharpId=Shader.PropertyToID("_GlassSharpBackdrop");
            sealed class Data{public TextureHandle source;public Material material;public int shaderPass;}
            public BackdropPass(Material material)
            {
                this.material=material;requiresIntermediateTexture=true;
                ConfigureInput(ScriptableRenderPassInput.Color);
            }
            public override void RecordRenderGraph(RenderGraph graph,ContextContainer frame)
            {
                var resources=frame.Get<UniversalResourceData>();
                var source=resources.activeColorTexture;
                if(resources.isActiveTargetBackBuffer||!source.IsValid())return;
                var desc=graph.GetTextureDesc(source);
                desc.msaaSamples=MSAASamples.None;desc.bindTextureMS=false;
                desc.clearBuffer=false;desc.depthBufferBits=DepthBits.None;
                desc.name="Glass RGBA scene copy";var sharp=graph.CreateTexture(desc);
                Add(graph,source,sharp,2,false);
                desc.width=Mathf.Max(1,desc.width/2);desc.height=Mathf.Max(1,desc.height/2);
                desc.name="Glass RGBA horizontal";var horizontal=graph.CreateTexture(desc);
                desc.name="Glass RGBA diffusion";var diffusion=graph.CreateTexture(desc);
                Add(graph,source,horizontal,0,false);
                Add(graph,horizontal,diffusion,1,true);
            }
            void Add(RenderGraph graph,TextureHandle source,TextureHandle destination,int index,bool export)
            {
                using(var builder=graph.AddRasterRenderPass<Data>(index==0?"Glass horizontal diffusion":"Glass vertical diffusion",out var data))
                {
                    data.source=source;data.material=material;data.shaderPass=index;
                    builder.UseTexture(source,AccessFlags.Read);
                    builder.SetRenderAttachment(destination,0,AccessFlags.WriteAll);
                    builder.AllowPassCulling(false);
                    if(export)builder.SetGlobalTextureAfterPass(destination,TextureId);
                    if(index==2)builder.SetGlobalTextureAfterPass(destination,SharpId);
                    builder.SetRenderFunc(static(Data d,RasterGraphContext context)=>
                        Blitter.BlitTexture(context.cmd,d.source,new Vector4(1,1,0,0),d.material,d.shaderPass));
                }
            }
        }
    }
}

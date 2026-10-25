using System.Collections.Generic;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace SpatialModeling
{
    public sealed class GlassGraphicRaycaster : GraphicRaycaster
    {
        public override void Raycast(PointerEventData data,List<RaycastResult> results)
        {
            var canvas=GetComponent<Canvas>();var camera=eventCamera;
            if(canvas==null||camera==null||GetComponent<GlassCurvedCanvas>()==null){base.Raycast(data,results);return;}
            var ray=camera.ScreenPointToRay(data.position);
            foreach(var graphic in GraphicRegistry.GetGraphicsForCanvas(canvas))
            {
                if(graphic==null||!graphic.raycastTarget||!graphic.isActiveAndEnabled||graphic.depth<0||graphic.canvasRenderer.cull)continue;
                if(!GlassRaycast.Hit(graphic.rectTransform,ray,out float distance,out _))continue;
                bool blocked=false;
                foreach(var group in graphic.GetComponentsInParent<CanvasGroup>())
                {if(!group.blocksRaycasts){blocked=true;break;}if(group.ignoreParentGroups)break;}
                if(blocked)continue;
                results.Add(new RaycastResult{gameObject=graphic.gameObject,module=this,distance=distance,index=results.Count,
                    depth=graphic.depth,sortingLayer=canvas.sortingLayerID,sortingOrder=canvas.sortingOrder,
                    worldPosition=ray.GetPoint(distance),worldNormal=-graphic.transform.forward,screenPosition=data.position});
            }
        }
    }
}

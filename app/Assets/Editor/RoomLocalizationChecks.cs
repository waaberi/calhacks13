using System;
using SpatialModeling;
using UnityEngine;

public static class RoomLocalizationChecks
{
    static void Check(bool value,string message) {if(!value) throw new Exception("Room localization: "+message);}
    static readonly Guid RoomA=new Guid("594979cb-451c-47f3-a518-904355523938");
    static readonly Guid RoomB=new Guid("4bbd0f2e-f460-42b8-aed0-e1210f95abb4");
    static WorkspaceRoomLocalization.FloorCandidate Floor(Guid room)
        => new WorkspaceRoomLocalization.FloorCandidate
        {
            Room=room,WorldPose=new Pose(Vector3.zero,Quaternion.Euler(90,0,0)),
            Boundary=new[]{new Vector2(-2,-2),new Vector2(2,-2),new Vector2(2,0),
                Vector2.zero,new Vector2(0,2),new Vector2(-2,2)},Tracked=true,SampleTime=10,
            CeilingHeight=2.5f
        };
    static bool Select(WorkspaceRoomLocalization.FloorCandidate[] floors,Vector3 head,out Guid room,bool ready=true,double now=10)
        => WorkspaceRoomLocalization.TrySelectRoom(floors,new Pose(head,Quaternion.identity),ready,now,out room,out _);
    public static void Run()
    {
        var floor=Floor(RoomA);
        Check(Select(new[]{floor},new Vector3(-1,1,-1),out var selected) && selected==RoomA,"actual concave floor interior selects known room");
        Check(!Select(new[]{floor},new Vector3(1,1,1),out selected) && selected==Guid.Empty,"concave missing corner rejects even singleton room");
        Check(!Select(new[]{floor},new Vector3(4,1,0),out selected),"single saved room cannot accept outside wearer");
        Check(!Select(new[]{floor},new Vector3(-1,4,-1),out selected),"another storey cannot pass two-dimensional containment");
        Check(!Select(new[]{floor},new Vector3(-1,2.6f,-1),out selected),"measured ceiling bounds apply");
        Check(!Select(new[]{floor},new Vector3(-1,-.1f,-1),out selected),"head below floor rejected");
        Check(!Select(new[]{floor},new Vector3(-1,1,-1),out selected,false),"unworn or unfocused or untracked head rejected");
        Check(!Select(new[]{floor},new Vector3(-1,1,-1),out selected,true,10.5),"stale anchor sample rejected");
        Check(!Select(new[]{floor},new Vector3(-1,1,-1),out selected,true,9),"future anchor sample rejected");
        var other=Floor(RoomB);
        Check(!Select(new[]{floor,other},new Vector3(-1,1,-1),out selected) && selected==Guid.Empty,"overlapping room matches rejected");
        Check(Select(new[]{floor,floor},new Vector3(-1,1,-1),out selected) && selected==RoomA,"duplicate observation is not a different room");
        other.WorldPose.position=new Vector3(10,0,0);
        Check(Select(new[]{other,floor},new Vector3(-1,1,-1),out selected) && selected==RoomA,"selection is independent of discovery order");
        var unknown=floor;unknown.Room=Guid.Empty;
        Check(!Select(new[]{unknown},new Vector3(-1,1,-1),out selected),"unknown floor room rejected");
        var lost=floor;lost.Tracked=false;
        Check(!Select(new[]{lost},new Vector3(-1,1,-1),out selected),"untracked floor rejected");
        var vertical=floor;vertical.WorldPose.rotation=Quaternion.identity;
        Check(!Select(new[]{vertical},new Vector3(-1,1,-1),out selected),"vertical or implausibly tilted floor rejected");
        var invalid=floor;invalid.Boundary=null;
        Check(!Select(new[]{invalid},new Vector3(-1,1,-1),out selected),"missing actual polygon has no rectangle fallback");
        invalid.Boundary=new[]{Vector2.zero,Vector2.one,Vector2.one*2};
        Check(!Select(new[]{invalid},new Vector3(-1,1,-1),out selected),"degenerate floor rejected");
        invalid.Boundary=new[]{Vector2.zero,new Vector2(float.NaN,0),Vector2.up};
        Check(!Select(new[]{invalid},new Vector3(-1,1,-1),out selected),"nonfinite polygon rejected");
        invalid=floor;invalid.WorldPose.rotation=new Quaternion(0,0,0,0);
        Check(!Select(new[]{invalid},new Vector3(-1,1,-1),out selected),"invalid floor pose rejected");
        Check(!Select(new[]{floor},new Vector3(float.PositiveInfinity,1,0),out selected),"nonfinite head rejected");
        var world=new Pose(new Vector3(7,2,-3),Quaternion.Euler(0,93,0));
        var transformed=floor;
        transformed.WorldPose=new Pose(world.position+world.rotation*floor.WorldPose.position,world.rotation*floor.WorldPose.rotation);
        Check(Select(new[]{transformed},world.position+world.rotation*new Vector3(-1,1,-1),out selected) && selected==RoomA,
            "floor and head share translated rotated world frame");
        Check(WorkspaceRoomLocalization.BelongsToRoom(RoomA,RoomA,Guid.Empty),"known matching surface allowed");
        Check(!WorkspaceRoomLocalization.BelongsToRoom(RoomB,RoomA,RoomA),"other room mesh rejected");
        Check(!WorkspaceRoomLocalization.BelongsToRoom(Guid.Empty,Guid.Empty,RoomA),"singleton never localizes unknown mesh");
        Check(WorkspaceRoomLocalization.BelongsToRoom(Guid.Empty,RoomA,RoomA),"unknown mesh may inherit unique already localized room");
        Check(!WorkspaceRoomLocalization.BelongsToRoom(Guid.Empty,RoomA,Guid.Empty),"unknown multiroom mesh rejected");
        Check(!WorkspaceRoomLocalization.BelongsToRoom(Guid.Empty,RoomA,RoomB),"singleton identity must match localized room");
        Debug.Log("ROOM_LOCALIZATION_CHECKS PASS actual_boundary concavity current_room outside_room vertical_bounds freshness ambiguity unknown_mesh physical_fit=UNVERIFIED");
    }
}

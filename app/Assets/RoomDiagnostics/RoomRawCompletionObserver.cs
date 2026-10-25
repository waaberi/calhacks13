using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using UnityEngine.XR.OpenXR.NativeTypes;

namespace SpatialModeling.Diagnostics
{
    // Safe managed facade. The sole unsafe assembly observes Unity's existing
    // event router; it never polls events, hooks dispatch or retains native memory.
    public sealed class RoomRawCompletionObserver : IDisposable
    {
        public readonly struct Sample
        {
            public readonly ulong Request;
            public readonly int Result,Component;
            public readonly bool Enabled;
            public Sample(ulong request,int result,int component,bool enabled)
            {Request=request;Result=result;Component=component;Enabled=enabled;}
        }
        readonly Registration registration;
        RoomRawCompletionObserver(Registration value) {registration=value;}
        public static bool TryBegin(Action<Sample> callback,out RoomRawCompletionObserver observer,int maximum=44)
        {
            observer=null;
            if(callback==null || maximum<1 || maximum>44 || !ValidateNativeLayout()) return false;
            var value=new Registration(callback,maximum);
            try
            {
                if(!value.Subscribe()) return false;
                observer=new RoomRawCompletionObserver(value);return true;
            }
            catch(Exception) {value.Dispose();return false;}
        }
        public void TrackRequest(ulong request) => registration.Track(request);
        public void Dispose() => registration.Dispose();

        [StructLayout(LayoutKind.Sequential)]
        struct NativeCompletion
        {
            public int Type;
            public IntPtr Next;
            public ulong Request;
            public int Result;
            public ulong Space;
            public Guid Uuid;
            public int Component;
            public uint Enabled;
        }
        public static bool ValidateNativeLayout()
            => IntPtr.Size==8 && Marshal.SizeOf<NativeCompletion>()==64
                && Marshal.OffsetOf<NativeCompletion>(nameof(NativeCompletion.Request)).ToInt32()==16
                && Marshal.OffsetOf<NativeCompletion>(nameof(NativeCompletion.Result)).ToInt32()==24
                && Marshal.OffsetOf<NativeCompletion>(nameof(NativeCompletion.Space)).ToInt32()==32
                && Marshal.OffsetOf<NativeCompletion>(nameof(NativeCompletion.Uuid)).ToInt32()==40
                && Marshal.OffsetOf<NativeCompletion>(nameof(NativeCompletion.Component)).ToInt32()==56
                && Marshal.OffsetOf<NativeCompletion>(nameof(NativeCompletion.Enabled)).ToInt32()==60;

        sealed unsafe class Registration : IDisposable
        {
            const XrStructureType EventType=XrStructureType.EventDataSpaceSetStatusCompleteFB;
            readonly Action<Sample> receive;
            readonly XrPollEventCallback callback;
            readonly HashSet<ulong> requests=new HashSet<ulong>();
            int remaining;
            bool subscribed,disposed;
            public Registration(Action<Sample> receive,int maximum)
            {this.receive=receive;remaining=maximum;callback=OnEvent;}
            public bool Subscribe() => subscribed=PollEventRouter.TrySubscribeToEventType(EventType,callback);
            public void Track(ulong request)
            {if(!disposed && request!=0 && requests.Count<44) requests.Add(request);}
            public void OnEvent(XrEventDataBaseHeader* header)
            {
                // Router iterates its subscriber collection. Do not unsubscribe
                // from inside this callback, even when its bounded quota expires.
                if(disposed || remaining<=0 || header==null || header->type!=EventType) return;
                try
                {
                    var value=*(NativeCompletion*)header;
                    if(value.Component!=0 || !requests.Remove(value.Request)) return;
                    remaining--;
                    receive(new Sample(value.Request,value.Result,value.Component,value.Enabled!=0));
                }
                catch(Exception) { /* Diagnostics cannot interrupt XR dispatch. */ }
            }
            public void Dispose()
            {
                if(disposed) return;
                disposed=true;requests.Clear();
                if(!subscribed) return;
                subscribed=false;
                try {PollEventRouter.TryUnsubscribeFromEventType(EventType,callback);}
                catch(Exception) { /* Loader teardown already clears subscriptions. */ }
            }
        }
        // Exercises the same callback and ABI decoder without a loader or native
        // polling. No pointer escapes; application tests call a safe managed API.
        public static unsafe bool VerifyDecoder()
        {
            if(!ValidateNativeLayout()) return false;
            int count=0;Sample copy=default;
            var value=new Registration(sample=>{count++;copy=sample;},2);
            var data=new NativeCompletion {Type=(int)XrStructureType.EventDataSpaceSetStatusCompleteFB,
                Request=42,Result=1,Component=0,Enabled=1};
            value.OnEvent((XrEventDataBaseHeader*)&data);
            if(count!=0) return false; // Unowned native requests are ignored.
            value.Track(42);value.OnEvent((XrEventDataBaseHeader*)&data);
            data.Result=-2;
            if(count!=1 || copy.Result!=1 || !copy.Enabled || copy.Request!=42) return false;
            value.OnEvent((XrEventDataBaseHeader*)&data);
            if(count!=1) return false; // Duplicate completion is ignored.
            value.Track(43);data.Request=43;value.OnEvent((XrEventDataBaseHeader*)&data);
            value.Track(44);data.Request=44;value.OnEvent((XrEventDataBaseHeader*)&data);
            if(count!=2) return false; // Diagnostic quota is enforced.
            value.Dispose();value.Dispose();return true;
        }
    }
}

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace SpatialModeling.VoiceCore
{
    // Read amounts from the preserved user's request, never from an aliased
    // quaternion. This validates intent only and never compiles an operation.
    public static class VoiceRotationLimits
    {
        const string Verbs=@"\b(?:rotate|turn|spin|add|create|make|move|scale|resize|extrude|inset|bevel|knife|cut|merge|dissolve|delete|remove|duplicate|reset|set|colou?r|paint|shade|snap|align|mirror|apply)\b";
        public static bool TryRead(string request,double maximumDegrees,out int amounts,out string error,bool allowMissing=false)
        {
            amounts=0;error=null;
            // Questions are app prose, never user intent. Keep every original
            // request and user answer, including a separately supplied unit.
            string text=Regex.Replace(request??"",@"(?im)^Clarification question:[^\r\n]*(?:\r?\n|$)","");
            text=Regex.Replace(text,@"(?im)^User answer:\s*","").ToLowerInvariant();
            var verbs=new List<Match>();
            foreach(Match match in Regex.Matches(text,Verbs))
            {
                if(match.Value=="turn"&&Regex.IsMatch(text.Substring(0,match.Index),@"\b(?:full|half|quarter|one|two|three|four|five|six|seven|eight|nine|\d+)\s*$"))continue;
                verbs.Add(match);
            }
            for(int clause=0;clause<verbs.Count;clause++)
            {
                var verb=verbs[clause];if(verb.Value!="rotate"&&verb.Value!="turn"&&verb.Value!="spin")continue;
                int end=clause+1<verbs.Count?verbs[clause+1].Index:text.Length;
                string body=text.Substring(verb.Index+verb.Length,end-verb.Index-verb.Length);
                if(Regex.IsMatch(body,@"\b(?:thousand|million|billion)\b"))
                {error="State each rotation amount as a complete number in degrees";return false;}
                var words=new List<string>();foreach(Match word in Regex.Matches(body,@"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?|[a-z]+|°"))words.Add(word.Value);
                int found=0;
                for(int i=0;i<words.Count;i++)
                {
                    int next=i;double value;
                    if(double.TryParse(words[i],NumberStyles.Float,CultureInfo.InvariantCulture,out value))next++;
                    else if(words[i]=="half"||words[i]=="quarter"||words[i]=="full") {value=words[i]=="half"?.5:words[i]=="quarter"?.25:1;next++;}
                    else if(!NumberWords.TryRead(words,ref next,out value))continue;
                    if(next<words.Count&&words[next]=="full")next++;
                    double factor=0;
                    if(next<words.Count)
                    {
                        string unit=words[next];
                        if(unit=="degrees"||unit=="degree"||unit=="deg"||unit=="°")factor=1;
                        else if(unit=="radian"||unit=="radians"||unit=="rad")factor=180/Math.PI;
                        else if(unit=="turn"||unit=="turns"||unit=="revolution"||unit=="revolutions")factor=360;
                    }
                    // VoiceCore's established Rotate default is degrees when
                    // an amount is followed directly by its axis or clause end.
                    if(factor==0&&(next==words.Count||Regex.IsMatch(words[next],@"^(?:about|around|along|on|axis|x|y|z|then|and)$")))factor=1;
                    if(factor==0)continue;
                    double angle=Math.Abs(value*factor);found++;amounts++;
                    if(double.IsNaN(angle)||double.IsInfinity(angle)||angle==0||angle>maximumDegrees+1e-8)
                    {error="Requested rotation is outside the existing voice angle limit. State a nonzero angle of at most "+maximumDegrees.ToString(CultureInfo.InvariantCulture)+" degrees";return false;}
                    i=next;
                }
                if(found==0&&!allowMissing)
                {error="State a complete rotation with an explicit nonzero angle and unit, such as ninety degrees";return false;}
            }
            return true;
        }
    }
}

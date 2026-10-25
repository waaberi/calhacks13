using System;
using SpatialModeling;
using Xunit;

public class VoiceDialogTests
{
    [Theory]
    [InlineData("Add a cube to the scene.","add a cube")]
    [InlineData("create a cylinder in the scene!","add a cylinder")]
    [InlineData("Could you please add a cube to my scene?","add a cube")]
    [InlineData("Make another sphere for me.","add a sphere")]
    [InlineData("Would you create a cylinder please?","add a cylinder")]
    [InlineData("Could you add a cube and move it right?",null)]
    [InlineData("Make a cube twenty millimeters wide please.",null)]
    [InlineData("Put a cube here",null)]
    [InlineData("add a cube then delete the cylinder",null)]
    [InlineData("add a cube 20 millimeters wide",null)]
    [InlineData("add a cube and export it",null)]
    public void BasicCreationKeepsDefaultsOnlyForWholeSimpleRequests(string input,string expected)
        => Assert.Equal(expected,VoiceDialogPages.BasicCreation(input));

    [Fact]
    public void LongReviewPreservesEveryParameterAndOutputReferenceAcrossBoundedPages()
    {
        string content="";
        for(int i=0;i<24;i++)content+="step"+i+" mesh.inset inner_faces reference_"+i+" thickness_m:0.002\n";
        content+=new string('X',250);
        var pages=VoiceDialogPages.Build(content);
        Assert.True(pages.Length>1);
        foreach(string page in pages)
        {
            Assert.InRange(page.Split('\n').Length,1,9);
            foreach(string line in page.Split('\n'))Assert.InRange(line.Length,0,64);
        }
        Assert.Equal(content.Replace("\n","").Replace(" ",""),string.Join("",pages).Replace("\n","").Replace(" ",""));
    }
}

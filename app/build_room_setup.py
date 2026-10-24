"""Serialize a room-setup Unity build and restore generated project settings."""
import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target',choices=['windows','quest'])
    parser.add_argument('--editor',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--log',type=Path,required=True)
    parser.add_argument('--export-project',action='store_true',help='Export a Quest Gradle project for separately controlled packaging')
    parser.add_argument('--native-snapshot',type=Path)
    parser.add_argument('--room-replay',type=Path)
    args=parser.parse_args()
    if args.export_project and args.target!='quest':parser.error('--export-project requires the quest target')
    project=Path(__file__).resolve().parent
    output=args.output.resolve(); log=args.log.resolve()
    if output.is_relative_to(project.parent) or log.is_relative_to(project.parent):
        raise RuntimeError('Keep artifacts and evidence outside the source worktree')
    if output.exists(): raise RuntimeError('Use a new output path; preserve existing build evidence')
    output.parent.mkdir(parents=True,exist_ok=True);log.parent.mkdir(parents=True,exist_ok=True)
    tracked=subprocess.check_output(['git','ls-files','app/ProjectSettings','app/Assets/Settings','app/Assets/XR','app/Assets/Oculus','app/Assets/Resources'],cwd=project.parent,text=True).splitlines()
    paths=[project.parent/relative for relative in tracked]
    backup={p:p.read_bytes() for p in paths if p.is_file()}
    env=os.environ.copy()
    env['CALHACKS_ROOM_SETUP_EXPORT_PROJECT']='1' if args.export_project else '0'
    if args.target=='quest': env['CALHACKS_ROOM_SETUP_APK']=str(output)
    else: env['CALHACKS_P2_BUILD_PATH']=str(output)
    if args.native_snapshot:env['CALHACKS_P2_NATIVE_SNAPSHOT']=str(args.native_snapshot.resolve())
    if args.room_replay:env['CALHACKS_ROOM_REPLAY']=str(args.room_replay.resolve())
    command=[str(args.editor.absolute()),'-batchmode','-nographics','-quit','-projectPath',str(project),
             '-buildTarget','Android' if args.target=='quest' else 'Win64','-executeMethod',
             'QuestRoomSetupBuild.Android' if args.target=='quest' else 'P2Checks.Windows','-logFile',str(log)]
    startup=None
    if os.name=='nt':
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    result={'target':args.target,'output':str(output),'log':str(log),'export_project':args.export_project,'physical_fit':'UNVERIFIED'}
    try:
        process=subprocess.Popen(command,env=env,startupinfo=startup)
        print(json.dumps({'editor_pid':process.pid,**result}),flush=True)
        code=process.wait(); content=log.read_text(encoding='utf-8',errors='replace')
        expected='QUEST_ROOM_SETUP_BUILD Succeeded errors=0' if args.target=='quest' else 'P2_BUILD_RESULT Succeeded errors=0'
        output_ready=output.is_dir() if args.export_project else output.is_file()
        result.update(exit_code=code,passed=code==0 and expected in content and output_ready)
    finally:
        for path,data in backup.items():
            if not path.exists() or path.read_bytes()!=data:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        result['tracked_settings_restored']=True
        log.with_suffix('.result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
    if not result.get('passed'):raise SystemExit(1)


if __name__=='__main__':main()

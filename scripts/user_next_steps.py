"""User-owned desktop loading steps after a successful restore."""
from pathlib import Path

from project_io import linked


NEXT_STEPS = '.rehome/NEXT_STEPS.md'
FAST_FORWARD_AFTERCARE = '确认目标会话没有运行中的进程后才快进。续聊后核对第一条新提问的 parentUuid 是否连到追加历史最后一条带 UUID 的记录。'
FIRST_MESSAGE = '这是迁移过来的同一条对话的继续。请根据上面的历史，用一句话说出我们上次做到哪里，然后等我下一步指示。'


def package_next_steps(package):
    """What the user does with a finished package; the package may hold private chats and source."""
    return {
        'title': '⚠ 打包完成，还差接收',
        'package_path': str(package),
        'same_computer': '打开目标 Agent，把下面这句话发给它。',
        'other_computer': '把整个包（文件或文件夹）复制到另一台电脑（U 盘、移动硬盘或局域网共享都可以），再把这句话发给那边的 Agent，路径换成包在那台电脑上的位置。那边也要先装好本 Skill 和 Python 3.10+。',
        'privacy': '包里有私人对话和项目文件，不要传到公开位置。',
        'first_message': f'用 Agent Rehome 接收这个搬家包：{package}',
    }


def add_next_steps(result, agent, project, titles):
    if agent == 'claude':
        heading = '⚠ 还差一步：请重启 Claude 桌面版'
        instructions = [
            '等当前工作完成后再退出。Windows 在系统托盘右键点击 Claude 图标，选择退出，再打开 Claude。',
            'macOS 按 Cmd+Q 退出 Claude，再重新打开。',
            '接收端会确认会话可见并指明一条恢复会话。请打开该会话，粘贴并发送下面的首句。若弹出「信任此文件夹」，请核对路径并亲自选择信任。',
        ]
        options = ['已重启，继续', '稍后再说']
    else:
        heading = '⚠ 还差一步：等待接收端完成 Codex 项目归组'
        instructions = [
            '接收端 Agent 会从官方入口打开目录，匹配项目根，按 ID 加载、归组并复查。',
            '如需信任，接收端会指明对应恢复会话。请打开该会话并发送下面的首句，出现「信任此文件夹」时核对路径并亲自确认。',
        ]
        options = ['已打开，继续', '稍后再说']
    steps = {'title':heading,'instructions':instructions,'project_path':str(project),
             'session_titles':list(titles),'first_message':FIRST_MESSAGE,'options':options}
    result['user_next_steps'] = steps
    path = Path(project) / NEXT_STEPS
    if any((p.exists() or p.is_symlink()) and linked(p) for p in (path.parent,path)):
        steps['file_status'] = 'linked-path-skipped'
        return
    lines = ['# '+heading, '', *instructions, '', '项目目录', '', str(project), '', '恢复会话', '']
    lines.extend('- '+title.replace('\r',' ').replace('\n',' ') for title in steps['session_titles'])
    lines.extend(['', '在恢复会话中发送的第一句话', '', '> '+FIRST_MESSAGE, ''])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write('\n'.join(lines))
    except FileExistsError:
        steps['file_status'] = 'existing-file-preserved'
    except OSError:
        steps['file_status'] = 'write-unavailable'
    else:
        steps['file'] = str(path)

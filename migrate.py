# -*- coding: utf-8 -*-
"""
项目迁移步骤：

1. 整理 commit message (http://yangtingpretty.blog.163.com/blog/static/18057748620129182316220/)
    1. 把 fix issues #xx 改为 fix #xx  (https://help.github.com/articles/interactive-rebase | git rebase -i | multi reword)
    2. 把 fix 了某些 issue 但忘了写在 message 里的给补上。如 fix by tag 0.3
    3. 把 fix #11, #22 改成 fix #11, fix #22  要不然对 #22 不生效
2. git rebase 后 commit hash 会改变，如果在 issue/comment 里引用到了，也要做相应改变
3. 在 github 中创建项目，不导入代码
4. 执行此脚本导入 issues
5. 导入代码（在这途中，被 fix 的 issues 会被自动关闭）
6. 执行另一个脚本或手动关闭那些不是被自动关闭的 issues
    1. 关闭 bitbucket 中为 resolved 但到现在为为止，github 中还是 open 的 issue（也就是 bitbucket 中被手动关闭的 issues）
    1. 关闭 wontfix issues
    2. 创建 onhold label，应用到对应的 issue

先把所有 issue 创建完，然后再创建 comments
因为有些 comment 会引用在当前 issue 之后创建的 issue，例如：#20 的 comment 可能会引用 #21
在 issue/comment A 中引用另一个 issue B 时，github 会在 B 处显示一条提醒，而这在引用之后创建的 issue 时无效
"""
# This file is part of the bitbucket issue migration script.
# 
# The script is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# The script is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with the bitbucket issue migration script.
# If not, see <http://www.gnu.org/licenses/>.

from github import Github
from datetime import datetime, timedelta
import requests
import time
import sys
import json
from optparse import OptionParser
import re
import os


# ===== 解析参数 =====

parser = OptionParser()

parser.add_option("-t", "--dry-run", action="store_true", dest="dry_run", default=False,
    help="Preform a dry run and print eveything.")

parser.add_option("-r", "--reindex", action="store_true", dest="reindex", default=False,
    help="when cache exists, clean it and get issues/comments data again from bitbucket")

parser.add_option("-g", "--github-username", dest="github_username",
    help="GitHub username")

parser.add_option("-d", "--github_repo", dest="github_repo",
    help="GitHub to add issues to. Format: <username>/<repo name>")

parser.add_option("-s", "--bitbucket_repo", dest="bitbucket_repo",
    help="Bitbucket repo to pull data from.")

parser.add_option("-u", "--bitbucket_username", dest="bitbucket_username",
    help="Bitbucket username")

(opt, _) = parser.parse_args()

#github_password = raw_input('Please enter your github password: ')
github_password = 'jsan0821'


# ===== 从 bitbucket 提取数据 =====

def bitbucket_api(res_url):
    url = 'https://bitbucket.org/api/1.0' + res_url
    print url
    return requests.get(url).json()


def get_issues():
    issues = []
    while True:
        result = bitbucket_api("/repositories/{}/{}/issues/?limit=45&start={}".format(opt.bitbucket_username, opt.bitbucket_repo, len(issues)))
        if not result['issues']:
            # Check to see if there is issues to process if not break out.
            break

        issues.extend(result['issues'])
    # issue 排序
    issues = sorted(issues, key=lambda issue: issue['local_id'])
    return issues


def get_comments(issue_id):
    comments = bitbucket_api("/repositories/{}/{}/issues/{}/comments".format(
        opt.bitbucket_username, opt.bitbucket_repo, issue_id))
    # 修正 comment 顺序
    comments.reverse()
    return comments


def extract_data():
    cache_exists = os.path.isfile('cache.json')

    # 清理缓存
    if cache_exists and opt.reindex:
        os.remove('cache.json')
        cache_exists = False

    if not cache_exists: # 若缓存不存在，从 bitbucket 提取 issues 及其 comments，建立缓存
        # [ [issue_data, comments_data] ]
        issue_pairs = [[issue, get_comments(issue['local_id'])] for issue in get_issues()]

        with open('cache.json', 'w+') as cache_file:
            cache_file.write(json.dumps(issue_pairs, indent=2, ensure_ascii=False))
    else:   # 若缓存存在，从缓存中提取数据
        with open('cache.json') as cache_file:
            issue_pairs = json.loads(cache_file.read())

    return issue_pairs


# ===== 在 Github 上创建 Issue、comment =====

def format_time(bitbucket_utc_time_str):
    t = datetime.strptime(bitbucket_utc_time_str[:-6], '%Y-%m-%d %H:%M:%S') + timedelta(hours=8)
    return datetime.strftime(t, '%Y-%m-%d %H:%M:%S')


# Login in to github and create object
github = Github(opt.github_username, github_password)
repo = github.get_repo(opt.github_repo)

labels = {}
for label in repo.get_labels():
    labels[label.name] = label

issue_count = 0

for issue, comments in extract_data():
    issue_count += 1
    # 创建 issue
    data = {}
    data['title'] = issue['title']
    data['assignee'] = opt.github_username

    data['body'] = issue['content'] + "\n\n\ncreated: " + format_time(issue['utc_created_on'])
    if issue['metadata']['kind'] not in ['bug', 'enhancement']:
        data['body'] += "\nkind: " + issue['metadata']['kind']

    issue_labels = []
    issue_labels.append(labels['bug'] if issue['metadata']['kind'] == 'bug' else labels['enhancement'])
    if issue['status'] in ['duplicate', 'invalid', 'wontfix']:
        issue_labels.append(labels[issue['status']])
    data['labels'] = issue_labels

    if opt.dry_run:
        print u"Title: {}".format(data['title'])
        print u"Body: {}".format(data['body'])
        print "Comments"
    else:
        issue_obj = repo.create_issue(**data)
        #if issue['status'] in ['resolved', 'duplicate', 'invalid', 'wontfix']:
        #    issue_obj.edit(state='closed')

    # 创建 comment
    comments_count = 0
    for comment in comments:
        if not comment['content']:
            continue
        comments_count += 1

        content = comment['content']
        
        match = re.search(ur'→ <<cset (\w{12})>>', content)
        if match is not None:
            #content = re.sub(ur'→ <<cset (\w{12})>>', '', content)
            #content = "\n".join(["> " + line for line in content.split("\n")]) # add blockquate
            #content = u"resolved by {}\n\n".format(match.groups()[0]) + content
            continue

        created = format_time(comment['utc_created_on'])
        updated = format_time(comment['utc_updated_on'])
        content += "\n\n\ncreated: " + created
        if updated != created:
            content += "\nlast updated: " + updated
        
        if opt.dry_run:
            print content + "\n\n"
        else:
            issue_obj.create_comment(content)

    print u"Created: {} with {} comments".format(data['title'], comments_count)

print "Created {0} issues".format(issue_count)

sys.exit()
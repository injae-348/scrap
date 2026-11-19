#!/bin/bash
# 리뷰어 에이전트(qa-reviewer, security-reviewer)용 PreToolUse 훅.
# Write/Edit 대상이 docs/reviews/ 안의 .md 파일이 아니면 차단한다 (exit 2).
input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')
project_dir="${CLAUDE_PROJECT_DIR:-$(printf '%s' "$input" | jq -r '.cwd // empty')}"

if [ -z "$file_path" ] || [ -z "$project_dir" ]; then
  echo "차단: 파일 경로를 확인할 수 없습니다." >&2
  exit 2
fi

# 상대 경로는 프로젝트 기준으로, .. 등은 정규화
case "$file_path" in
  /*) ;;
  *) file_path="$project_dir/$file_path" ;;
esac
resolved=$(python3 -I -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$file_path")
allowed=$(python3 -I -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$project_dir/docs/reviews")

case "$resolved" in
  "$allowed"/*.md) exit 0 ;;
esac

echo "차단: 리뷰어는 docs/reviews/*.md 에만 쓸 수 있습니다 (요청 경로: $file_path). 코드 수정이 필요하면 결과 문서에 수정 제안으로 적으세요." >&2
exit 2

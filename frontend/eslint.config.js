import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

// 렌더링 안전·토큰 보관 규칙 (앱 소스에만 적용. 테스트는 결과 HTML을 읽어야 하므로 뺀다)
const HTML_SINK_MSG = '제목·메모·URL을 HTML로 넣지 않는다. React 텍스트 렌더링이나 안전 컴포넌트를 쓴다.'
const STORAGE_MSG = '브라우저 저장소를 쓰지 않는다. 인증은 서버의 HttpOnly 쿠키뿐이다.'

export default defineConfig([
  globalIgnores(['dist', 'dev-dist', 'coverage']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat['recommended-latest'],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/**/*.test.{ts,tsx}'],
    rules: {
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      'no-restricted-syntax': [
        'error',
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: HTML_SINK_MSG },
        { selector: "JSXAttribute[name.name=/^src[dD]oc$/]", message: HTML_SINK_MSG },
        { selector: "MemberExpression[property.name=/^(innerHTML|outerHTML|srcdoc)$/]", message: HTML_SINK_MSG },
        { selector: "MemberExpression[property.value=/^(innerHTML|outerHTML|srcdoc)$/]", message: HTML_SINK_MSG },
        {
          selector: "CallExpression[callee.property.name=/^(insertAdjacentHTML|createContextualFragment|setHTMLUnsafe)$/]",
          message: HTML_SINK_MSG,
        },
        {
          selector: "CallExpression[callee.object.name='document'][callee.property.name=/^(write|writeln)$/]",
          message: HTML_SINK_MSG,
        },
        { selector: "Identifier[name=/^(localStorage|sessionStorage|indexedDB)$/]", message: STORAGE_MSG },
      ],
      'no-restricted-properties': [
        'error',
        { object: 'document', property: 'cookie', message: STORAGE_MSG },
      ],
    },
  },
])

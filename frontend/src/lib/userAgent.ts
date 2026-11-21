// 세션 목록의 user_agent 원문을 "iPhone · Safari"처럼 짧게 바꾼다. 화면 표시용 추정일 뿐이다.

export function describeUserAgent(ua: string): string {
  const s = ua || ''
  let device = ''
  if (/iPhone/i.test(s)) device = 'iPhone'
  else if (/iPad/i.test(s)) device = 'iPad'
  else if (/Android/i.test(s)) device = /Mobile/i.test(s) ? 'Android 휴대폰' : 'Android 태블릿'
  else if (/Macintosh|Mac OS X/i.test(s)) device = 'Mac'
  else if (/Windows/i.test(s)) device = 'Windows'
  else if (/CrOS/i.test(s)) device = 'Chromebook'
  else if (/Linux/i.test(s)) device = 'Linux'

  let browser = ''
  if (/Edg(e|A|iOS)?\//i.test(s)) browser = 'Edge'
  else if (/SamsungBrowser/i.test(s)) browser = '삼성 인터넷'
  else if (/Whale\//i.test(s)) browser = 'Whale'
  else if (/OPR\/|Opera/i.test(s)) browser = 'Opera'
  else if (/Firefox\/|FxiOS/i.test(s)) browser = 'Firefox'
  else if (/CriOS|Chrome\//i.test(s)) browser = 'Chrome'
  else if (/Safari\//i.test(s) || /AppleWebKit/i.test(s)) browser = 'Safari'
  else if (/curl|python|httpx|okhttp/i.test(s)) browser = '프로그램'

  const label = [device, browser].filter(Boolean).join(' · ')
  return label || '알 수 없는 기기'
}

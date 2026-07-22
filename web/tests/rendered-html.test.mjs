import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    {
      ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the anonymous Framecheck core workflow", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="zh-CN">/i);
  assert.match(html, /<title>帧检 Framecheck｜短视频交付质检<\/title>/i);
  assert.match(html, /本地处理/);
  assert.match(html, /把成片拖到这里/);
  assert.match(html, /type="file"[^>]*accept="video\/\*,\.mov,\.m4v"/i);
  assert.match(html, /开始质检/);
  assert.match(html, /视频仅在当前浏览器中解码，不会离开你的设备/);
  assert.doesNotMatch(html, /signin-with-chatgpt|signout-with-chatgpt|登录后使用|requireChatGPTUser/i);
  assert.doesNotMatch(html, /Your site is taking shape|Codex is working|react-loading-skeleton/i);
});

test("keeps analysis browser-local and free of authentication guards", async () => {
  const [page, analyzer, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/video-analyzer.ts", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(packageJson, /"name": "framecheck-web"/);
  assert.match(page, /type="file"/);
  assert.match(page, /analyzeVideo\(videoFile, captionFile/);
  assert.match(page, /URL\.createObjectURL\(file\)/);
  assert.match(analyzer, /document\.createElement\("video"\)/);
  assert.match(analyzer, /AudioContext|webkitAudioContext/);
  assert.doesNotMatch(page + analyzer, /fetch\s*\(|XMLHttpRequest|signin-with-chatgpt|requireChatGPTUser/i);
});

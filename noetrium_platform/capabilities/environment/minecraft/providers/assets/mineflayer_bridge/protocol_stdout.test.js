'use strict'

const assert = require('node:assert/strict')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const test = require('node:test')

test('bridge reserves stdout exclusively for JSONL protocol frames', () => {
  const bridge = path.join(__dirname, 'bridge.js')
  const result = spawnSync(
    process.execPath,
    [bridge],
    {
      input: '{definitely-not-json}\n',
      encoding: 'utf8',
      env: process.env,
      timeout: 5000
    }
  )

  assert.equal(result.error, undefined)
  assert.equal(result.status, 0)
  const lines = String(result.stdout || '')
    .split(/\r?\n/)
    .filter(Boolean)
  assert.ok(lines.length >= 1)
  for (const line of lines) {
    const value = JSON.parse(line)
    assert.equal(typeof value, 'object')
    assert.equal(value.protocol_version, 'minecraft-jsonl-v1')
  }
  assert.match(String(result.stderr || ''), /(?:^|\n|.)*/)
})

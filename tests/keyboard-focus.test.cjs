// Local, offline DOM tests. This uses Playwright's bundled headless Chromium;
// it never opens the user's browser/profile or contacts ChatGPT.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const hook = fs.readFileSync(path.join(__dirname, '..', 'keyboard-focus.js'), 'utf8');
const fixture = `
  <style>input,textarea,button,label,div[contenteditable],iframe {display:block;margin:8px;min-height:28px}</style>
  <input id="prompt" value="PRIVATE_TEST_VALUE">
  <input id="search" type="search">
  <textarea id="textarea"></textarea>
  <label for="search" id="label"><span>Search label</span></label>
  <div contenteditable="true" id="editor"><span id="editable-child">editor</span><span id="noneditable" contenteditable="false">locked</span></div>
  <input id="readonly" readonly>
  <fieldset disabled><input id="fieldset-input"></fieldset>
  <input id="checkbox" type="checkbox">
  <div aria-readonly="true" role="textbox"><div contenteditable="true" id="aria-readonly">locked</div></div>
  <div role="textbox" id="role-only">read-only presentation</div>
  <div inert><input id="inert-input"></div>
  <div id="shadow-host"></div>
  <button id="outside">Outside</button>
  <button id="submit" onclick="setTimeout(() => document.querySelector('#prompt').focus(), 0)">Send</button>
  <iframe id="child" srcdoc="<input id='child-input'>"></iframe>`;

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ hasTouch: true, viewport: { width: 1000, height: 1600 } });
  await context.route('**/*', route => route.abort());
  const page = await context.newPage();
  const signals = [];
  await page.exposeBinding('__foldgptImeSignal', ({ frame }, payload) => {
    const signal = JSON.parse(payload);
    assert.deepEqual(Object.keys(signal).sort(), ['reason', 'sequence', 'visible']);
    assert.equal(payload.includes('PRIVATE_TEST_VALUE'), false);
    signals.push({ ...signal, main: frame === page.mainFrame() });
  });
  try {
    await page.setContent(fixture);
    await page.evaluate(() => {
      const root = document.querySelector('#shadow-host').attachShadow({ mode: 'open' });
      root.innerHTML = '<input id="shadow-input">';
      document.querySelector('#prompt').focus();
    });
    await page.evaluate(hook);
    assert.equal(signals.length, 0, 'attach never opens an already-focused input');

    // Browser touch events exercise real DOM editability. Force the touch for
    // disabled fields that Playwright correctly refuses to fill or focus.
    for (const [selector, expected] of [
      ['#prompt', true], ['#search', true], ['#textarea', true],
      ['#editable-child', true], ['#label span', true], ['#shadow-input', true],
      ['#readonly', false], ['#fieldset-input', false], ['#checkbox', false],
      ['#aria-readonly', false], ['#role-only', false], ['#inert-input', false],
      ['#noneditable', false], ['#outside', false],
    ]) {
      signals.length = 0;
      await page.locator(selector).tap({force: true});
      await page.waitForTimeout(20);
      assert.equal(signals.some(s => s.visible), expected, selector);
    }
    await page.locator('#shadow-host').evaluate(node => node.setAttribute('inert', ''));
    signals.length = 0;
    await page.locator('#shadow-input').tap({force: true});
    assert.equal(signals.at(-1).visible, false, 'inert crosses the shadow host');
    await page.locator('#shadow-host').evaluate(node => node.removeAttribute('inert'));

    await page.locator('#prompt').tap();
    signals.length = 0;
    await page.locator('#prompt').tap();
    assert(signals.some(s => s.reason === 'pointer' && s.visible), 'same-field tap reopens the IME');
    await page.locator('#outside').tap();
    await page.waitForTimeout(20);
    assert.equal(signals.at(-1).visible, false, 'outside touch dismisses');

    await page.locator('#search').tap();
    signals.length = 0;
    await page.evaluate(hook);
    assert.equal(signals.length, 0, 'reconnect never reopens a retained editable focus');

    // Regression: Send dismisses the IME, then ChatGPT refocuses its prompt.
    // Both delayed refocus and later resume/focus signals must leave it hidden.
    await page.locator('#prompt').tap();
    signals.length = 0;
    await page.locator('#submit').tap();
    await page.waitForTimeout(20);
    assert.equal(await page.locator('#prompt').evaluate(node => node === document.activeElement), true);
    assert.equal(signals.at(-1).visible, false, 'Send dismisses despite prompt refocus');
    assert.equal(signals.some(s => s.visible), false, 'programmatic refocus never requests opening');
    signals.length = 0;
    await page.evaluate(() => {
      window.dispatchEvent(new Event('focus'));
      document.dispatchEvent(new Event('visibilitychange'));
      document.querySelector('#prompt').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}));
    });
    await page.evaluate(hook);
    assert.equal(signals.some(s => s.visible), false, 'resume/reconnect/synthetic pointers cannot reopen');
    await page.locator('#prompt').tap();
    assert.equal(signals.at(-1).visible, true, 'a later deliberate touch reopens the prompt');

    // Moving between editable fields does not close an already-open keyboard.
    signals.length = 0;
    await page.locator('#search').focus();
    await page.waitForTimeout(20);
    assert.equal(signals.length, 0, 'editable handover preserves current IME state');

    const child = page.frames().find(frame => frame !== page.mainFrame());
    await child.evaluate(hook);
    signals.length = 0;
    await child.locator('#child-input').tap();
    await page.waitForTimeout(20);
    assert.equal(signals.at(-1).visible, true, 'child focus is not undone by parent blur: ' + JSON.stringify(signals));
    assert.equal(signals.at(-1).main, false);

    await page.locator('#outside').tap();
    await page.waitForTimeout(20);
    assert.equal(signals.at(-1).visible, false, 'leaving a frame dismisses');
    const settled = signals.length;
    await page.waitForTimeout(50);
    assert.equal(signals.length, settled, 'hook is event-driven and idle after settling');

    // Disposal removes anonymous listeners and pending callbacks; sequence IDs
    // remain increasing across installation so the daemon accepts the upgrade.
    const previousSequence = signals.filter(s => s.main).at(-1).sequence;
    await page.evaluate(() => globalThis.__foldgptImeV5.dispose());
    signals.length = 0;
    await page.locator('#prompt').tap();
    await page.waitForTimeout(20);
    assert.equal(signals.length, 0, 'disposed hook has no remaining listeners');
    await page.evaluate(hook);
    assert.equal(signals.length, 0, 'installing replacement does not reopen');
    await page.locator('#prompt').tap();
    assert.equal(signals.length, 1, 'replacement installs exactly one pointer listener');
    assert.equal(signals[0].visible, true);
    assert(signals[0].sequence > previousSequence, 'sequence survives hook upgrades');
    assert(signals.filter(s => s.visible).every(s => s.reason === 'pointer'));
    console.log('PASS: deliberate touch only, Send/refocus regression, handover/re-tap, readonly/inert/shadow/frame handling, disposal/upgrades and metadata privacy');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

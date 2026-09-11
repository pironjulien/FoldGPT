(() => {
  const key = '__foldgptImeV5';
  if (globalThis[key]) {
    globalThis[key].resync();
    return 'already-installed';
  }
  // Subsequent versions can remove every listener before installing a new hook.
  // V4 did not expose disposal and needs one document reload when upgrading.
  globalThis.__foldgptImeHook?.dispose();
  const controller = new AbortController();
  const signal = controller.signal;
  const sequenceKey = '__foldgptImeSequence';
  globalThis[sequenceKey] ??= 0;
  let disposed = false;
  let pending;
  const textTypes = new Set(['text', 'search', 'email', 'url', 'tel', 'password', 'number']);
  function parent(node) {
    return node.parentElement || node.getRootNode()?.host;
  }
  function editable(node) {
    if (!(node instanceof Element)) return false;
    // Roles alone do not make a node editable. Respect restrictions across
    // shadow boundaries as well as native disabled fieldsets.
    for (let ancestor = node; ancestor instanceof Element; ancestor = parent(ancestor)) {
      if (ancestor.hasAttribute('inert') || ancestor.getAttribute('aria-disabled') === 'true' ||
          ancestor.getAttribute('aria-readonly') === 'true') return false;
    }
    if (node.matches('input')) return !node.matches(':disabled') && !node.readOnly && textTypes.has(node.type);
    if (node.matches('textarea')) return !node.matches(':disabled') && !node.readOnly;
    return node.isContentEditable;
  }
  function active() {
    let node = document.activeElement;
    while (node?.shadowRoot?.activeElement) node = node.shadowRoot.activeElement;
    return node;
  }
  function report(visible, reason) {
    if (disposed) return;
    // Focusing the prompt after Send is application behavior, not a request to
    // type again. Opening is reserved for a trusted pointer event below.
    if (visible && reason !== 'pointer') return;
    // A trusted pointerdown may precede document focus when entering an iframe.
    // Its user gesture is sufficient; retained background focus never gets here.
    if (visible && document.visibilityState !== 'visible') return;
    // No values, labels, field contents or keystrokes are transmitted.
    globalThis.__foldgptImeSignal(JSON.stringify({visible, reason, sequence: ++globalThis[sequenceKey]}));
  }
  function reportCurrent(reason) {
    const node = active();
    // The child document owns its focus signal. A parent's delayed focusout
    // must not race the child's focusin and dismiss its keyboard.
    if (node?.matches('iframe,frame')) return;
    // Preserve a keyboard that is already open during field handover. Never
    // infer that retained/programmatic focus should reopen a dismissed keyboard.
    if (!editable(node)) report(false, reason);
  }
  document.addEventListener('pointerdown', event => {
    if (!event.isTrusted) return;
    clearTimeout(pending);
    let node = event.composedPath().find(item => item instanceof Element);
    const label = node?.closest('label');
    if (label?.control) node = label.control;
    // Repeat taps reopen an already-focused field after manual IME dismissal.
    report(editable(node), 'pointer');
  }, {capture: true, signal});
  document.addEventListener('focusin', () => {
    clearTimeout(pending);
    reportCurrent('focus');
  }, {capture: true, signal});
  document.addEventListener('focusout', () => {
    clearTimeout(pending);
    // Let focus move between fields before deciding whether to dismiss the keyboard.
    pending = setTimeout(() => reportCurrent('blur'), 0);
  }, {capture: true, signal});
  document.addEventListener('visibilitychange', () => {
    clearTimeout(pending);
    if (document.visibilityState === 'visible') reportCurrent('resume');
    else report(false, 'hidden');
  }, {signal});
  window.addEventListener('focus', () => {
    clearTimeout(pending);
    // Entering an iframe focuses its window before its input. Let that focusin
    // settle before a body activeElement can dismiss the user's pointer request.
    pending = setTimeout(() => reportCurrent('window-focus'), 0);
  }, {signal});
  window.addEventListener('blur', () => {
    clearTimeout(pending);
    pending = setTimeout(() => {
      if (!document.hasFocus()) report(false, 'window-blur');
    }, 0);
  }, {signal});
  const instance = {
    resync: () => reportCurrent('attach'),
    dispose: () => {
      disposed = true;
      clearTimeout(pending);
      controller.abort();
      if (globalThis[key] === instance) delete globalThis[key];
      if (globalThis.__foldgptImeHook === instance) delete globalThis.__foldgptImeHook;
    }
  };
  globalThis[key] = instance;
  globalThis.__foldgptImeHook = instance;
  reportCurrent('attach');
  return 'installed';
})();

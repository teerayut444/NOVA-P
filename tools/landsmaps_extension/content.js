// All Asset Dashboard - LandsMaps 100% Zero-Click Auto-Fill Script
(function () {
  'use strict';

  function runAutoFill() {
    const hash = window.location.hash.substring(1);
    if (!hash) return;

    const params = new URLSearchParams(hash);
    const prov = decodeURIComponent(params.get('prov') || '').trim();
    const dist = decodeURIComponent(params.get('dist') || '').trim();
    const deed = decodeURIComponent(params.get('deed') || '').trim();
    const caseNo = decodeURIComponent(params.get('case') || '').trim();

    if (!prov && !dist && !deed) return;

    console.log('[All Asset] Auto-Fill initiated:', { prov, dist, deed, caseNo });

    function clean(s) {
      return (s || '').replace(/^(จังหวัด|จ\.|อำเภอ|อ\.|เขต)/g, '').trim().toLowerCase();
    }

    function showBanner(prefix, detailText, isSuccess, duration = 6000) {
      let b = document.getElementById('all-asset-autofill-banner');
      if (!b) {
        b = document.createElement('div');
        b.id = 'all-asset-autofill-banner';
        b.style.position = 'fixed';
        b.style.top = '18px';
        b.style.left = '50%';
        b.style.transform = 'translateX(-50%)';
        b.style.zIndex = '99999999';
        b.style.padding = '12px 26px';
        b.style.borderRadius = '12px';
        b.style.fontFamily = "'Noto Sans Thai', Sarabun, sans-serif, system-ui";
        b.style.fontSize = '14px';
        b.style.fontWeight = 'bold';
        b.style.boxShadow = '0 12px 32px rgba(0,0,0,0.35)';
        b.style.transition = 'all 0.3s ease';
        b.style.display = 'flex';
        b.style.alignItems = 'center';
        b.style.gap = '10px';
        document.body.appendChild(b);
      }
      b.style.backgroundColor = isSuccess ? '#059669' : '#0284c7';
      b.style.color = '#ffffff';
      b.textContent = '';
      if (prefix) {
        const strong = document.createElement('b');
        strong.textContent = prefix;
        b.appendChild(strong);
      }
      if (detailText) {
        const span = document.createElement('span');
        span.textContent = detailText;
        b.appendChild(span);
      }
      setTimeout(() => {
        if (b) {
          b.style.opacity = '0';
          setTimeout(() => b.remove(), 400);
        }
      }, duration);
    }

    function findBestOption(selectEl, targetClean, provClean) {
      if (!selectEl || !targetClean) return null;
      const opts = Array.from(selectEl.options).filter(o => {
        const t = clean(o.text);
        return t && o.value !== '' && !t.includes('เลือก') && !t.includes('--');
      });
      // 1. Exact normalized match
      const exact = opts.find(o => clean(o.text) === targetClean);
      if (exact) return exact;
      // 2. Disambiguate "เมือง" -> "เมือง{จังหวัด}"
      if (targetClean === 'เมือง' && provClean) {
        const muangTarget = 'เมือง' + provClean;
        const muangOpt = opts.find(o => clean(o.text) === muangTarget);
        if (muangOpt) return muangOpt;
      }
      // 3. Longest prefix/suffix substring match only when target is >= 2 chars
      if (targetClean.length >= 2 && targetClean !== 'เมือง') {
        const matches = opts.filter(o => {
          const t = clean(o.text);
          return t.includes(targetClean) || targetClean.includes(t);
        });
        if (matches.length > 0) {
          matches.sort((a, b) => Math.abs(clean(a.text).length - targetClean.length) - Math.abs(clean(b.text).length - targetClean.length));
          return matches[0];
        }
      }
      return null;
    }

    showBanner('⚡ All Asset Dashboard:', `กำลังเลือก ${prov ? 'จ.' + prov : ''} ${dist ? 'อ.' + dist : ''} ให้อัตโนมัติ...`.trim(), false);

    const cProv = clean(prov);
    const cDist = clean(dist);

    let checkCount = 0;
    const maxChecks = 60; // 60 * 250ms = 15 seconds max wait

    const checkInterval = setInterval(() => {
      checkCount++;

      const selects = Array.from(document.querySelectorAll('select'));
      if (selects.length === 0) {
        if (checkCount >= maxChecks) clearInterval(checkInterval);
        return;
      }

      // 1. Locate Province Dropdown
      const provSel = selects.find(s => {
        const id = (s.id || '').toLowerCase();
        const n = (s.name || '').toLowerCase();
        return id.includes('prov') || n.includes('prov') || Array.from(s.options).some(o => o.text.includes('กรุงเทพ') || o.text.includes('จังหวัด'));
      }) || selects[0];

      if (!provSel || provSel.options.length <= 1) {
        if (checkCount >= maxChecks) clearInterval(checkInterval);
        return;
      }

      // Find province option
      const provOpt = findBestOption(provSel, cProv, '');

      if (provOpt && provSel.value !== provOpt.value) {
        provSel.value = provOpt.value;
        provSel.dispatchEvent(new Event('change', { bubbles: true }));
        if (window.jQuery) {
          try { window.jQuery(provSel).trigger('change'); } catch(e) {}
        }
        console.log('[All Asset] Selected Province:', provOpt.text);
      }

      // 2. Locate District Dropdown
      const curSelects = Array.from(document.querySelectorAll('select'));
      const distSel = curSelects.find(s => {
        const id = (s.id || '').toLowerCase();
        const n = (s.name || '').toLowerCase();
        return s !== provSel && (id.includes('amp') || id.includes('dist') || n.includes('amp') || n.includes('dist') || Array.from(s.options).some(o => o.text.includes('อำเภอ') || o.text.includes('เขต')));
      }) || curSelects[1];

      if (distSel && distSel.options.length > 1) {
        const distOpt = findBestOption(distSel, cDist, cProv);

        if (distOpt) {
          clearInterval(checkInterval);
          distSel.value = distOpt.value;
          distSel.dispatchEvent(new Event('change', { bubbles: true }));
          if (window.jQuery) {
            try { window.jQuery(distSel).trigger('change'); } catch(e) {}
          }
          console.log('[All Asset] Selected District:', distOpt.text);

          // 3. Deed Number Handling
          const deedInp = document.querySelector('input[placeholder*="โฉนด"], input[name*="deed"], input[id*="deed"]') ||
            Array.from(document.querySelectorAll('input[type="text"]')).find(i => (i.placeholder || '').includes('โฉนด'));

          if (deed && deedInp) {
            deedInp.value = deed;
            deedInp.dispatchEvent(new Event('input', { bubbles: true }));
            deedInp.dispatchEvent(new Event('change', { bubbles: true }));

            // Trigger Search
            setTimeout(() => {
              const btn = Array.from(document.querySelectorAll('button, input[type="button"], a')).find(b => (b.innerText || b.value || '').includes('ค้นหา'));
              if (btn) btn.click();
              showBanner('✅ ค้นหาสำเร็จ:', `จ.${prov} อ.${dist} | โฉนดเลขที่ ${deed}`, true, 8000);
            }, 350);
          } else {
            if (deedInp) deedInp.focus();
            const caseText = caseNo ? ` (คดี: ${caseNo})` : '';
            showBanner('✅ เลือกให้อัตโนมัติแล้ว:', `จ.${prov} อ.${dist}${caseText}`, true, 8000);
          }
        }
      }

      if (checkCount >= maxChecks) {
        clearInterval(checkInterval);
      }
    }, 250);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runAutoFill);
  } else {
    runAutoFill();
  }

  window.addEventListener('hashchange', runAutoFill);
})();

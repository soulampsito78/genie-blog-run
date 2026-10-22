"""Pure bounds/diagnostics regression; never runs feeds, models or delivery."""
import __future__
import ast
from pathlib import Path
import re
import unittest
from typing import Any,Dict,List

ROOT=Path(__file__).resolve().parents[1]

def pure():
    text=(ROOT/'keysuri_live_source_smoke.py').read_text();tree=ast.parse(text)
    roots={'_items_per_feed_for_program','_bounded_prompt_hold_reason_codes','_prompt_input_diagnostic_snapshot'}
    defs={}
    for n in tree.body:
        if isinstance(n,ast.FunctionDef):defs[n.name]=n
        elif isinstance(n,ast.Assign):
            for t in n.targets:
                if isinstance(t,ast.Name):defs[t.id]=n
    needed=set(roots)
    while True:
        deps={x.id for k in needed for x in ast.walk(defs[k]) if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Load) and x.id in defs}
        if deps<=needed:break
        needed|=deps
    ns={'re':re,'Any':Any,'Dict':Dict,'List':List}
    nodes=[n for n in tree.body if any(n is defs[k] for k in needed)]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'pure selection diagnostics','exec',flags=__future__.annotations.compiler_flag),ns)
    return ns,text

class SelectionCapacityAndDiagnosticsTests(unittest.TestCase):
    def setUp(self):self.ns,self.text=pure()
    def test_korea_uses_six_entries_per_existing_feed(self):
        self.assertEqual(self.ns['_items_per_feed_for_program']('keysuri_korea_tech'),6)
    def test_korea_alias_keeps_same_bound(self):
        self.assertEqual(self.ns['_items_per_feed_for_program']('keysuri_korea_alias'),6)
    def test_global_budget_is_not_changed(self):
        self.assertEqual(self.ns['_items_per_feed_for_program']('keysuri_global_tech'),self.ns['GLOBAL_ITEMS_PER_FEED'])
    def test_unrecognized_program_keeps_existing_default(self):
        self.assertEqual(self.ns['_items_per_feed_for_program']('unknown'),3)
    def test_early_hold_code_survives_without_funnel(self):
        snapshot=self.ns['_prompt_input_diagnostic_snapshot']({'prompt_status':'hold_review_required','top_5_news':None,'prompt_hold_reason_codes':['insufficient_top_news_candidates']})
        self.assertEqual(snapshot['prompt_hold_reason_codes'],['insufficient_top_news_candidates'])
        self.assertNotIn('candidate_funnel_summary',snapshot)
        self.assertIsNone(snapshot['hold_reason'])
    def test_selection_issue_code_is_fallback_not_raw_message(self):
        snapshot=self.ns['_prompt_input_diagnostic_snapshot']({'top_5_selection_result':{'verdict':'hold','issues':[{'code':'business_implication_missing','message':'PRIVATE CONTENT MUST NOT LEAK'}]}})
        self.assertEqual(snapshot['prompt_hold_reason_codes'],['business_implication_missing'])
        self.assertNotIn('PRIVATE',repr(snapshot))
    def test_invalid_or_secret_like_codes_are_not_copied(self):
        codes=self.ns['_bounded_prompt_hold_reason_codes']({'prompt_hold_reason_codes':['Bearer secret','a@b.test','한글',None,17,'valid_code']})
        self.assertEqual(codes,['valid_code'])
    def test_reason_codes_are_unique_and_bounded(self):
        codes=self.ns['_bounded_prompt_hold_reason_codes']({'prompt_hold_reason_codes':['same','same']+['code_'+str(i) for i in range(20)]})
        self.assertEqual(len(codes),8);self.assertEqual(codes.count('same'),1)
    def test_ready_snapshot_not_turned_into_hold(self):
        data={'prompt_status':'ready_for_generation','top_5_news':{'items':[{'news_id':'x','headline':'headline'}]}}
        snapshot=self.ns['_prompt_input_diagnostic_snapshot'](data)
        self.assertEqual(snapshot['prompt_status'],'ready_for_generation');self.assertNotIn('prompt_hold_reason_codes',snapshot)
    def test_readiness_guard_still_returns_before_generation(self):
        tree=ast.parse(self.text);runner=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_keysuri_live_source_smoke')
        guard=next(n for n in runner.body if isinstance(n,ast.If) and "ready_for_generation" in ast.get_source_segment(self.text,n.test))
        self.assertTrue(any(isinstance(n,ast.Return) for n in guard.body))
        self.assertTrue(any(isinstance(n,ast.keyword) and n.arg=='ok' and isinstance(n.value,ast.Constant) and n.value.value is False for n in ast.walk(guard)))

if __name__=='__main__':unittest.main()

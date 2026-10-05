"""Serial exact-copy publication adapter for the sole central wave dispatcher.

The new phase uses a distinct tag hash and records its changed execution regime.
All original Run identities and original plan hash remain bound. No model is
called here, and no legacy pair journal or recursive cohort lock is used.
"""
from pathlib import Path

from outer.harness import util
from research import catalog_share, next_phase_sharing, pair_execution, wave_plan


class Publisher:
    def __init__(self, dispatcher, *, preservation_contract=None):
        self.dispatcher = dispatcher
        self.repo = dispatcher.repo
        self.original_path = Path(dispatcher.phase['original_bundle']['path'])
        self.preservation_contract = preservation_contract
        if preservation_contract is not None:
            from research import preservation_gate
            preservation_gate.validate_contract(preservation_contract, current=dispatcher.current())

    def workspace(self, number):
        if self.preservation_contract is not None:
            if number != 53: raise ValueError('Preservation publisher is exact53 only')
            return self.repo / 'artifacts/continuity-sharing-v1/wave-053-preservation-v7'
        return self.repo / 'artifacts/continuity-sharing-v1' / f'wave-{number:03d}'

    def context(self, repo, original_path, number):
        d = self.dispatcher
        if (Path(repo).resolve() != d.repo or Path(original_path).resolve() != self.original_path.resolve()
                or not d.entered):
            raise ValueError('Authoritative central phase session required')
        current = d.current()
        if not current['waves'] or number not in current['waves'][-1]['pairs'] or not current['barrier']:
            raise ValueError('Publication requires the stopped current wave')
        original = util.read_json(self.original_path)
        pair = next(p for p in original['assignments'] if p['pair'] == number)
        bindings = [current['dispatch'].get(c['run_id'], {}) for c in pair['cases']]
        if any(b.get('plan_sha256') != d.phase['original_bundle']['sha256']
                or b.get('phase_sha256') != d.digest or b.get('cohort') != d.phase['cohort']
                or c['run_id'] not in current['results']
                or current['implementations'][c['run_id']]['receipt'].get('stop_confirmed') is not True
                or current['implementations'][c['run_id']]['receipt'].get('submission_fixed') is not True
                for c, b in zip(pair['cases'], bindings)):
            raise ValueError('Current pair must have two bound, stopped, fixed terminal results')
        return original, d.batch, current, pair, bindings

    def metadata(self, number):
        d = self.dispatcher
        current = d.current()
        soak_phase = d.phase
        while soak_phase['kind'] in (wave_plan.V4_KIND, wave_plan.V5_KIND, wave_plan.V6_KIND, wave_plan.V7_KIND):
            soak_phase = util.read_json(soak_phase['predecessor_phase']['path'])
        disclosure = {}
        if self.preservation_contract is not None:
            from research import preservation_gate
            disclosure['preservation_disposition'] = preservation_gate.public_disclosure(self.preservation_contract)
        return {'phase_id': d.phase['phase_id'], 'phase_sha256': d.digest,
            'source_commit': d.phase['source_commit'],
            'original_bundle_sha256': d.phase['original_bundle']['sha256'],
            'completed_earlier_pairs': d.phase['completed_pairs'],
            'initial_pairs': d.phase['initial_pairs'], 'maximum_pairs': d.phase['maximum_pairs'],
            'internal_concurrency': d.phase['internal_concurrency'], 'no_refill': True,
            'responsibility': d.phase['shards'][str(number)],
            'wave_pair_numbers': current['waves'][-1]['pairs'],
            'configured_wave_run_cap': current['waves'][-1]['run_cap'],
            'operational_policy_sha256': d.phase['operational_policy']['sha256'],
            **({'predecessor_phase_sha256': d.phase['predecessor_phase']['sha256'],
                'predecessor_journal_sha256': d.phase['predecessor_journal']['sha256'],
                'resource_probe_sha256': d.phase['resource_probe']['sha256']}
               if d.phase.get('predecessor_phase') else {}),
            **({'ancestor_phase_sha256s': [r['sha256'] for r in wave_plan.ancestor_references(d.phase)],
                'cause_condition_acceptance_sha256': soak_phase['resource_collector_acceptance']['sha256'],
                'actual_soak_verification_sha256': d.phase['actual_soak_verification']['sha256']}
               if d.phase['kind'] in (wave_plan.V3_KIND, wave_plan.V4_KIND, wave_plan.V5_KIND, wave_plan.V6_KIND, wave_plan.V7_KIND) else {}),
            **({'probe_repair_acceptance_sha256': d.phase['resource_collector_acceptance']['sha256'],
                'soak_binding': 'Historical ancestor v3 probe only; does not authorize current v'
                    + str(d.phase['schema_version']) + ' probe bytes'}
               if d.phase['kind'] in (wave_plan.V4_KIND, wave_plan.V5_KIND, wave_plan.V6_KIND, wave_plan.V7_KIND) else {}),
            **disclosure,
            'evaluator_diagnostics': d.phase.get('evaluator_diagnostics'),
            'limitation': 'Shared resource/provider concurrency is a separate execution condition; historical pairs1–'
                + str(max(d.phase['completed_pairs'])) + ' and their earlier execution phases are preserved without rescoring.'}

    def ready(self, number, current):
        d = self.dispatcher
        workspace = self.workspace(number)
        self.context(d.repo, self.original_path, number)
        if not workspace.exists():
            next_phase_sharing.stage(d.repo, self.original_path, number, workspace,
                                    context=self.context, phase=self.metadata(number))
        review = workspace / 'public-review.json'
        if not review.is_file():
            return False
        # Finalization may already have safely removed the reviewed copies. Its
        # exact review and evidence bindings are verified in finish(), not rebuilt.
        if (workspace / 'finalization.json').is_file():
            return True
        saved = util.read_json(review)
        if (saved.get('publication_approved') is not True
                or saved.get('pair') != number
                or saved.get('plan_sha256') != d.phase['original_bundle']['sha256']
                or saved.get('reviewed_inventory') != catalog_share.inventory(workspace / 'public')):
            raise ValueError('Exact approved public inventory/identity required')
        manifest = catalog_share.verify_public(workspace / 'public', exact=True)
        if manifest.get('execution_phase') != self.metadata(number):
            raise ValueError('Reviewed public copy belongs to a different wave phase')
        return True

    def publish(self, number, current, recovering):
        if not self.ready(number, current):
            raise ValueError('Central dispatcher must hold for exact public review')
        d = self.dispatcher
        workspace = self.workspace(number)

        def verify_gate(batch, pair_number, path):
            if Path(batch).resolve() != d.batch or pair_number != number:
                raise ValueError('Foreign publication gate')
            gate = util.read_json(path)
            pair_execution._validate_gate(gate, d.current(), number)
            if gate.get('phase_sha256') != d.digest:
                raise ValueError('Generic public gate must bind this phase')
            # Dispatcher.finish_wave writes the single authoritative phase event
            # immediately after this operation. Never append to the old journal.

        result = next_phase_sharing.share(d.repo, self.original_path, number, workspace,
            workspace / 'public-review.json', context=self.context, phase=self.metadata(number),
            record_gate=verify_gate, preservation_contract=self.preservation_contract)
        if result.get('status') != 'shared_downloaded_restored_extracted_cleaned':
            raise ValueError('Actual publication/anonymous restore/cleanup gate incomplete')
        return Path(result['gate'])

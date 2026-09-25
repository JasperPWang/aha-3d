import copy
import unittest
from tools.human_experiments.build_portal import validate_review


class ReviewRolesTest(unittest.TestCase):
    def setUp(self):
        self.case = dict(frames=302, source_video='source.mp4', variants=[
            dict(id='baseline', video='baseline.mp4'),
            dict(id='retained', video='retained.mp4'),
            dict(id='joint', video='joint.mp4', status='rejected')], review=dict(
                previous_variant='retained', new_variants=['joint'], default_new_variant='joint',
                actor_hint='Distant man', verdict='Still rejected', change='Move the root',
                explanation='Original pose retained', source_caption='Target man',
                previous_caption='Retained control',
                watch_points=[dict(frame=245, label='Exit', explanation='Hide departed person')]))

    def test_rejected_new_result_is_playable_but_keeps_explicit_roles(self):
        validate_review(self.case)
        self.assertEqual(self.case['variants'][2]['status'], 'rejected')

    def test_previous_cannot_be_presented_as_new(self):
        for value in ['retained', 'unknown']:
            case=copy.deepcopy(self.case);case['review']['new_variants']=[value]
            with self.assertRaises(ValueError):validate_review(case)
        for video in ['source.mp4', 'retained.mp4', 'nested/../retained.mp4']:
            case=copy.deepcopy(self.case);case['variants'][2]['video']=video
            with self.assertRaisesRegex(ValueError, 'reuse'):validate_review(case)

    def test_duplicate_new_video_alias_is_not_two_experiments(self):
        self.case['variants'].append(dict(id='joint2', video='nested/../joint.mp4'))
        self.case['review']['new_variants'].append('joint2')
        with self.assertRaisesRegex(ValueError, 'reuse'):validate_review(self.case)

    def test_wrong_jump_time_and_default_fail(self):
        case=copy.deepcopy(self.case);case['review']['watch_points'][0]['frame']=302
        with self.assertRaisesRegex(ValueError, 'Watch point'):validate_review(case)
        case=copy.deepcopy(self.case);case['review']['default_new_variant']='baseline'
        with self.assertRaisesRegex(ValueError, 'roles'):validate_review(case)

    def test_legacy_case_can_remain_in_history(self):
        self.case.pop('review');validate_review(self.case)


if __name__ == '__main__':unittest.main()

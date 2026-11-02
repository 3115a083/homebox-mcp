"""No live deletions. Validate confirmation and empty-location guards."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

for key in list(os.environ):
    if 'proxy' in key.lower():
        os.environ.pop(key)
os.environ['HOMEBOX_TOKEN'] = 'unit-test-placeholder'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gateway'))
import bridge
import homebox_mcp as hb

location = {'id': 'location-id', 'path': 'Office/Testbox',
            'node': {'name': 'Testbox', 'children': []}}
with patch.object(hb, '_find_location', return_value=(location, None)), \
     patch.object(hb, '_search_all', return_value=[]), \
     patch.object(hb, '_delete_path') as delete:
    result = bridge.delete_empty_location('Office/Testbox', 'Falscher Name')
    assert 'error' in result and not delete.called
    result = bridge.delete_empty_location('Office/Testbox', 'Testbox')
    assert result['ok'] is True
    delete.assert_called_once_with('/entities/location-id')

for children, items in [([{'name': 'Unterbox'}], []), ([], [{'name': 'Schrauben'}])]:
    location['node']['children'] = children
    with patch.object(hb, '_find_location', return_value=(location, None)), \
         patch.object(hb, '_search_all', return_value=items), \
         patch.object(hb, '_delete_path') as delete:
        result = bridge.delete_empty_location('Office/Testbox', 'Testbox')
        assert 'error' in result and not delete.called

item = {'id': 'item-id', 'name': 'Testgeraet', 'assetId': '000-999'}
with patch.object(hb, '_resolve_exact', return_value=(item, None)), \
     patch.object(hb, '_is_location', return_value=False), \
     patch.object(hb, '_delete_path') as delete:
    result = hb.delete_item('000-999', 'Falscher Name')
    assert 'error' in result and not delete.called
    result = hb.delete_item('000-999', 'Testgeraet')
    assert result['ok'] is True
    delete.assert_called_once_with('/entities/item-id')

with patch.object(hb, '_tag_by_name', return_value={'id': 'tag-id', 'name': 'Testtag'}), \
     patch.object(hb, '_delete_path') as delete:
    result = hb.delete_tag('Testtag', 'Falscher Name')
    assert 'error' in result and not delete.called
    result = hb.delete_tag('Testtag', 'Testtag')
    assert result['ok'] is True
    delete.assert_called_once_with('/tags/tag-id')
print('PASS: exact-name confirmation; empty-only locations; blocked contents/sub-locations; item and tag confirmation. No live deletions.')

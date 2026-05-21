# TODO: Fix Lookup Master valueCount Issue

## Task
Modify the /lookup/master endpoint to return correct count of lookup values for each lookup category.

## Plan

### Step 1: Update LookupMasterResponse Schema ✅
- Add `valueCount: int = 0` field to `LookupMasterResponse` in `app/schemas/lookup_schema.py`

### Step 2: Update get_lookup_masters Service Function ✅
- Modify `get_lookup_masters` function in `app/services/lookup_service.py`
- Use LEFT JOIN between lookup_master and lookup_value
- Count only active values (is_active = True)
- Return valueCount in response

## Status: COMPLETED ✅

## Include Status --> main control goes to the user config -->the endpoint seperate value through the managing values ..


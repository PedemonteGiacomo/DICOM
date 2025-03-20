from pynetdicom import StoragePresentationContexts

# Print all available storage contexts
for i, context in enumerate(StoragePresentationContexts):
    print(f"{i}: {context.abstract_syntax.name}")
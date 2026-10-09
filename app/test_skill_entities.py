from skill_entities import SKILL_ENTITIES


def main():

    print("=" * 60)
    print("TALENTFORGE SKILL ENTITIES")
    print("=" * 60)

    print(
        f"\nTotal entities: {len(SKILL_ENTITIES)}"
    )

    for index, entity in enumerate(
        SKILL_ENTITIES,
        start=1
    ):

        print("\n" + "-" * 60)

        print(f"Entity: {index}")
        print(f"Name: {entity['name']}")
        print(f"Type: {entity['type']}")
        print(f"Description: {entity['description']}")

    print("\n" + "=" * 60)
    print("SKILL ENTITY DEFINITION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()